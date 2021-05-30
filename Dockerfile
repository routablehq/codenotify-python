FROM python:3.6.7-alpine as builder

COPY requirements.txt /requirements.txt
RUN pip install -r /requirements.txt

COPY main.py /main.py
ENTRYPOINT ["python", "/main.py"]
