# Python imports
import json
import os
import subprocess
from collections import namedtuple
from fnmatch import fnmatch

# Pip imports
import requests


BASE_PR_COMMENT = "👔 Code pros! Mind taking a look at this PR?\ncc:{}"
PR_COMMENT_TITLE = "<!-- codenotify report -->\n"
CODEPROS_FILE = "CODEPROS"

# Env vars
GITHUB_EVENT_PATH_ENV_VAR = "GITHUB_EVENT_PATH"
GITHUB_GRAPHQL_URL_ENV_VAR = "GITHUB_GRAPHQL_URL"
GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"
GITHUB_WORKSPACE_ENV_VAR = "GITHUB_WORKSPACE"


# GraphQL queries & mutations

GRAPHQL_GET_PR_COMMENTS = """
  query GetPullRequestComments ($nodeId: ID!) {
    node(id: $nodeId) {
     ... on PullRequest {
       comments(first: 100) {
         nodes {
           id
           author {
             login
           }
           body
         }
       }
     }
    }
  }
"""

GRAPHQL_GET_PR_COMMIT_COUNT = """
  query CommitCount ($nodeId: ID!) {
    node(id: $nodeId) {
      ... on PullRequest {
        commits {
          totalCount
        }
      }
    }
  }
"""


GRAPHQL_ADD_PR_COMMENT = """
  mutation AddComment ($subjectId: ID!, $body: String!) {
    addComment(input: {
      subjectId: $subjectId
      body: $body
    }) {
      clientMutationId
    }
  }
"""

GRAPHQL_UPDATE_PR_COMMENT = """
  mutation UpdateComment ($id: ID!, $body: String!) {
    updateIssueComment(input: {
      id: $id
      body: $body
    }) {
      clientMutationId
    }
  }
"""


# simple obj matching patterns over path strings (glob) to code pros
CodeProsGlob = namedtuple("CodeProsGlob", ("glob", "pros"))


def load_env_var(env_var):
    """ Load environment variable defined."""

    val = os.environ.get(env_var)
    if not val:
        raise EnvironmentError(f"Missing {env_var} environment variable")

    return val


class GitHubGraphQLClient:
    """ GitHub GraphQL client to access the GitHub GraphQL API."""

    def __init__(self):
        self._github_graphql_url = None
        self._github_token = None

    def make_request(self, query, variables):
        """ Make a GraphQL query to the GitHub API and return the JSON result."""

        try:
            body = json.dumps({"query": query, "variables": variables})
        except TypeError:
            raise TypeError("GitHub GraphQL query cannot be serialized from JSON.")

        response = requests.post(self.github_graphql_url, headers=self.headers, data=body)
        if response.status_code != requests.codes.ok:
            raise Exception(f"GitHub GraphQL Non-200 Response: {response.text}")

        return response.json()

    @property
    def github_graphql_url(self):
        if self._github_graphql_url is None:
            self._github_graphql_url = load_env_var(GITHUB_GRAPHQL_URL_ENV_VAR)

        return self._github_graphql_url

    @property
    def github_token(self):
        if self._github_token is None:
            self._github_token = load_env_var(GITHUB_TOKEN_ENV_VAR)

        return self._github_token

    @property
    def headers(self):
        return {"Authorization": f"bearer {self.github_token}"}


github_graphql_client = GitHubGraphQLClient()


def get_changed_files(github_dir, pr_id, base_ref, head_ref):
    """ Get a collection of files changed in this branch. """

    response = github_graphql_client.make_request(GRAPHQL_GET_PR_COMMIT_COUNT, {"nodeId": pr_id})
    commit_count = response["data"]["node"]["commits"]["totalCount"]

    # fetch all latest commits
    _ = subprocess.run(["git", "-C", github_dir, "-c", "protocol.version=2", "fetch", "--deepen", str(commit_count)])

    output = subprocess.getoutput(
            f"git -C {github_dir} diff --name-only {base_ref}...{head_ref}")

    return [changed_file for changed_file in output.split("\n") if changed_file]


def globulize_filepath(filepath):
    """ Take a filepath defined and if a specific file is not specified, make it greedy in glob format. """

    # remove leading slash
    if filepath[0] == "/":
        filepath = filepath[1:]

    # is targeting a file specifically, no change needed
    if "." in filepath.split("/")[-1]:
        return filepath

    # /src/ --> /src/*
    if filepath[-1] == "/":
        filepath += "*"
    # /src --> /src/*
    elif filepath[-1] != "*":
        filepath += "/*"

    return filepath


def get_code_pros_globs(codepros_location, ignore_pros):
    """ Build a collection of CodeProsGlob objects from the CODEPROS file ignoring any pros. """

    # CODEPROS file must be defined at the base level of the git repository
    if not os.path.exists(codepros_location):
        return []

    code_pro_globs = []
    with open(codepros_location) as codepros_file:
        for line in codepros_file:
            if line[0] == "#":  # commented out line
                continue

            pro_pattern_line = line[:-1].split(" ")

            if not pro_pattern_line[0]:
                if len(pro_pattern_line) == 1:  # empty line
                    continue

                raise IOError(f"CODEPROS file malformed, line missing file: \"{line}\"")

            filepath = pro_pattern_line[0]
            pros = set(pro_pattern_line[1:])

            pros -= ignore_pros
            if not pros:
                continue

            glob = globulize_filepath(filepath)

            for pro in pros:
                if pro[0] != "@" or len(pro) < 2:
                    raise IOError(f"CODEPROS file malformed, pro incorrect: \"{line}\"")

            code_pro_globs.append(CodeProsGlob(pros=pros, glob=glob))

    return code_pro_globs


def comment_on_pr(pr_id, pros):
    """ Add (or change) a comment on a PR to notify code pros by their GitHub handle. """

    response = github_graphql_client.make_request(GRAPHQL_GET_PR_COMMENTS, {"nodeId": pr_id})

    comment_id = None
    for comment in response["data"]["node"]["comments"]["nodes"]:
        if comment["body"].startswith(PR_COMMENT_TITLE):
            comment_id = comment["id"]
            break

    comment = BASE_PR_COMMENT.format(" ".join(pros))
    comment = f"{PR_COMMENT_TITLE}\n{comment}"

    if comment_id:  # update existing comment
        print(f"Updating comment pros to include {pros}")
        _ = github_graphql_client.make_request(
            GRAPHQL_UPDATE_PR_COMMENT,
            {"id": comment_id, "body": comment})
    else:  # add new comment
        print(f"Adding new comment with pros {pros}")
        _ = github_graphql_client.make_request(
            GRAPHQL_ADD_PR_COMMENT,
            {"subjectId": pr_id, "body": comment})


def get_github_event_data(path):
    """ Get the event data on the PR. """

    with open(path) as github_event_file:
        try:
            github_event_data = json.load(github_event_file)
        except json.JSONDecodeError:
            raise ValueError("GitHub event data cannot be deserialized to JSON.")

    if "pull_request" not in github_event_data:
        raise ValueError("GitHub event file is missing pull request data, is it configured correctly?")

    return github_event_data


def main():
    """ Main method. """

    github_dir = load_env_var(GITHUB_WORKSPACE_ENV_VAR)
    github_event_path = load_env_var(GITHUB_EVENT_PATH_ENV_VAR)

    github_event_data = get_github_event_data(github_event_path)
    if github_event_data["pull_request"]["draft"]:
        print("Not sending notifications for draft pull request.")
        return

    base_ref = github_event_data["pull_request"]["base"]["sha"]
    head_ref = github_event_data["pull_request"]["head"]["sha"]
    pr_author = "@" + github_event_data["pull_request"]["user"]["login"]
    pr_id = github_event_data["pull_request"]["node_id"]

    codepros_location = os.path.join(github_dir, CODEPROS_FILE)

    # do not notify this pr's author
    code_pro_globs = get_code_pros_globs(codepros_location, ignore_pros={pr_author})
    if not code_pro_globs:
        print("No CODEPROS globs found.")
        return

    pros = set()
    for changed_file in get_changed_files(github_dir, pr_id, base_ref, head_ref):
        for code_pro_glob in code_pro_globs:
            if fnmatch(changed_file, code_pro_glob.glob):
                print(f"Rule {code_pro_glob.glob} matches {changed_file}")
                pros |= code_pro_glob.pros

    print("No pros found for these files")
    if pros:
        comment_on_pr(pr_id, pros)


if __name__ == "__main__":
    main()
