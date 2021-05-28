FROM python:3.6.7-alpine as builder

RUN python main.py
