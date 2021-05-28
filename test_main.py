from unittest.mock import MagicMock, mock_open, patch
from main import (
    CODEPROS_FILE,
    GITHUB_GRAPHQL_URL_ENV_VAR,
    GITHUB_TOKEN_ENV_VAR,
    GRAPHQL_ADD_PR_COMMENT,
    GRAPHQL_UPDATE_PR_COMMENT,
    PR_COMMENT_TITLE,
    GitHubGraphQLClient,
    comment_on_pr,
    get_changed_files,
    get_code_pros_globs,
    get_github_event_data,
    globulize_filepath,
)
import os
import unittest


class TestGetChangedFiles(unittest.TestCase):

    @patch("subprocess.getoutput", return_value="")
    def test_no_files_returned(self, get_output):
        files = get_changed_files("/",
            "ffc33a2baaebb4aa1e8ab035f89050b186a2ad36",
            "d51184732797cbf1e3fc39b618e6f1688cc34a03")

        get_output.assert_called()
        self.assertEqual(files, [])


    @patch("subprocess.getoutput", return_value="main.py\ntest_main.py")
    def test_multiple_files_returned(self, get_output):
        files = get_changed_files("/",
            "ffc33a2baaebb4aa1e8ab035f89050b186a2ad36",
            "d51184732797cbf1e3fc39b618e6f1688cc34a03")

        get_output.assert_called()
        self.assertEqual(files, ["main.py", "test_main.py"])


class TestGlobulizeFilepath(unittest.TestCase):

    def test_file(self):
        glob_filepath = globulize_filepath("hello/world.js")
        self.assertEqual(glob_filepath, "hello/world.js")

    def test_directories(self):
        glob_filepath = globulize_filepath("hello/world/")
        self.assertEqual(glob_filepath, "hello/world/*")

        glob_filepath = globulize_filepath("hello/world")
        self.assertEqual(glob_filepath, "hello/world/*")


class TestCodeProsGlobs(unittest.TestCase):

    def test_empty_codepros_file(self):
        with patch("builtins.open", new_callable=mock_open, read_data="") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            code_pro_globs = get_code_pros_globs(CODEPROS_FILE, set())

        self.assertEqual(code_pro_globs, [])

    @patch("os.path.exists", return_value=False)
    def test_codepros_file_missing(self, path_exists):
        code_pro_globs = get_code_pros_globs(CODEPROS_FILE, set())
        self.assertIsNone(code_pro_globs)

    def test_codepros_file_missing_file(self):
        with patch("builtins.open", new_callable=mock_open, read_data=" @pro\n") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            with self.assertRaises(IOError) as ex:
                _ = get_code_pros_globs(CODEPROS_FILE, set())

            self.assertTrue("line missing file" in str(ex.exception))

    def test_codepros_file_bad_pro(self):
        with patch("builtins.open", new_callable=mock_open, read_data="main.py pro\n") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            with self.assertRaises(IOError) as ex:
                _ = get_code_pros_globs(CODEPROS_FILE, set())

            self.assertTrue("pro incorrect" in str(ex.exception))

    def test_remove_author(self):
        with patch("builtins.open", new_callable=mock_open, read_data="main.py @pro\ntest_main.py @pro2\n") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            code_pros_globs = get_code_pros_globs(CODEPROS_FILE, {"@pro2"})

        self.assertEqual(len(code_pros_globs), 1)
        self.assertEqual(code_pros_globs[0].pros, {"@pro"})
        self.assertEqual(code_pros_globs[0].glob, "main.py")

    def test_good_codepros_file(self):
        with patch("builtins.open", new_callable=mock_open, read_data="main.py @pro\ntest_main.py @pro\n") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            code_pros_globs = get_code_pros_globs(CODEPROS_FILE, set())

        self.assertEqual(len(code_pros_globs), 2)
        self.assertEqual(code_pros_globs[0].pros, {"@pro"})
        self.assertEqual(code_pros_globs[0].glob, "main.py")
        self.assertEqual(code_pros_globs[1].pros, {"@pro"})
        self.assertEqual(code_pros_globs[1].glob, "test_main.py")


class TestGitHubGraphQLClient(unittest.TestCase):

    def test_missing_env_vars(self):
        os.environ.pop(GITHUB_GRAPHQL_URL_ENV_VAR, None)
        os.environ.pop(GITHUB_TOKEN_ENV_VAR, None)

        with self.assertRaises(EnvironmentError) as ex:
            client = GitHubGraphQLClient()
            client.github_graphql_url

        with self.assertRaises(EnvironmentError) as ex:
            client = GitHubGraphQLClient()
            client.github_token

    def test_invalid_json_query(self):
        os.environ[GITHUB_GRAPHQL_URL_ENV_VAR] = "invalid_response"
        os.environ[GITHUB_TOKEN_ENV_VAR] = "invalid_response"

        with self.assertRaises(TypeError):
            client = GitHubGraphQLClient()
            client.make_request("---", set())

    @patch("requests.post", return_value=MagicMock(status_code=401))
    def test_invalid_response(self, requests_post):
        os.environ[GITHUB_GRAPHQL_URL_ENV_VAR] = "invalid_response"
        os.environ[GITHUB_TOKEN_ENV_VAR] = "invalid_response"
        client = GitHubGraphQLClient()

        with self.assertRaises(Exception) as ex:
            client.make_request("---", {"a": "b"})

        self.assertTrue(str(ex.exception).startswith("GitHub GraphQL Non-200 Response"))

    def test_valid_response(self):
        os.environ[GITHUB_GRAPHQL_URL_ENV_VAR] = "valid"
        os.environ[GITHUB_TOKEN_ENV_VAR] = "valid"
        client = GitHubGraphQLClient()

        with patch("requests.post") as requests_post_patch:
            response_mock = MagicMock(status_code=200)
            response_mock.json.return_value = {"a": "ok"}

            requests_post_patch.return_value = response_mock

            response = client.make_request("---", {"a": "b"})
            self.assertEqual(response, {"a": "ok"})


class TestCommentOnPR(unittest.TestCase):

    @patch(
        "main.github_graphql_client.make_request",
        return_value={"data": {"node": {"comments": {"nodes": [{"id": 1, "body": PR_COMMENT_TITLE}]}}}})
    def test_update_comment(self, github_graphql):
        comment_on_pr(123, "@pro")
        self.assertEqual(github_graphql.call_args[0][0], GRAPHQL_UPDATE_PR_COMMENT)

    @patch("main.github_graphql_client.make_request", return_value={"data": {"node": {"comments": {"nodes": []}}}})
    def test_add_new_comment(self, github_graphql):
        comment_on_pr(123, "@pro")
        self.assertEqual(github_graphql.call_args[0][0], GRAPHQL_ADD_PR_COMMENT)


class TestGetGitHubEventData(unittest.TestCase):

    def test_invalid_json(self):
        with patch("builtins.open", new_callable=mock_open, read_data="{{\n") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            with self.assertRaises(ValueError) as ex:
                event_data = get_github_event_data("event.json")

            self.assertTrue("cannot be deserialized" in str(ex.exception))

    def test_misconfigured_workflow(self):
        with patch("builtins.open", new_callable=mock_open, read_data="{\"foo\": \"bar\"}\n") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            with self.assertRaises(ValueError) as ex:
                event_data = get_github_event_data("event.json")

            self.assertTrue("missing pull request data" in str(ex.exception))

    def test_configured_workflow(self):
        with patch("builtins.open", new_callable=mock_open, read_data="{\"pull_request\": {\"draft\": false}}\n") as m:
            m.return_value.__iter__ = lambda self: self
            m.return_value.__next__ = lambda self: next(iter(self.readline, ''))

            event_data = get_github_event_data("event.json")
            self.assertFalse(event_data["pull_request"]["draft"])


if __name__ == "__main__":
    unittest.main()
