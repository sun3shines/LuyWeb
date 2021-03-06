import sys
import pytest
sys.path.append("..")

import asyncio
import inspect
import os
from aiofiles import os as async_os
from mimetypes import guess_type
from urllib.parse import unquote

import pytest
from random import choice

from luya import Luya
from luya.response import HTTPResponse, stream, HTTPStreamingResponse, json
from unittest.mock import MagicMock

JSON_DATA = {'ok': True}


def test_response_body_not_a_string():
    """Test when a response body sent from the application is not a string"""
    app = Luya('response_body_not_a_string')
    random_num = choice(range(1000))

    @app.route('/hello')
    async def hello_route(request):
        return HTTPResponse(body=random_num)

    response = app.test_client.get('/hello')
    assert response.text == str(random_num)


async def sample_streaming_fn(response):

    response.write('foo,')
    await asyncio.sleep(.001)
    response.write('bar')


@pytest.fixture
def json_app():
    app = Luya('json')

    @app.route("/")
    async def test(request):
        return json(JSON_DATA)

    return app


def test_json_response(json_app):
    from luya.response import json_dumps
    response = json_app.test_client.get('/')
    assert response.status == 200
    assert response.text == json_dumps(JSON_DATA)
    assert response.json == JSON_DATA


@pytest.fixture
def streaming_app():
    app = Luya('streaming')

    @app.route("/")
    async def test(request):
        return stream(sample_streaming_fn, content_type='text/csv')

    return app


def test_streaming_adds_correct_headers(streaming_app):
    response = streaming_app.test_client.get('/')
    assert response.headers['Transfer-Encoding'] == 'chunked'
    assert response.headers['Content-Type'] == 'text/csv'


def test_streaming_returns_correct_content(streaming_app):
    response = streaming_app.test_client.get('/')
    assert response.text == 'foo,bar'


@pytest.mark.parametrize('status', [200, 201, 400, 401])
def test_stream_response_status_returns_correct_headers(status):
    response = HTTPStreamingResponse(sample_streaming_fn, status=status)
    headers = response.compute_header()
    assert b"HTTP/1.1 %s" % str(status).encode() in headers


@pytest.mark.parametrize('keep_alive_timeout', [10, 20, 30])
def test_stream_response_keep_alive_returns_correct_headers(
        keep_alive_timeout):
    response = HTTPStreamingResponse(sample_streaming_fn)
    headers = response.compute_header(
        keep_alive=True, keep_alive_timeout=keep_alive_timeout)

    assert b"Keep-Alive: %s\r\n" % str(keep_alive_timeout).encode() in headers


def test_stream_response_includes_chunked_header():
    response = HTTPStreamingResponse(sample_streaming_fn)
    headers = response.compute_header()
    assert b"Transfer-Encoding: chunked\r\n" in headers


def test_stream_response_writes_correct_content_to_transport(streaming_app):
    response = HTTPStreamingResponse(sample_streaming_fn)
    response.transport = MagicMock(asyncio.Transport)

    @streaming_app.listener('after_start')
    async def run_stream(app, loop):
        await response.stream_output()
        assert response.transport.write.call_args_list[1][0][0] == (
            b'4\r\nfoo,\r\n'
        )

        assert response.transport.write.call_args_list[2][0][0] == (
            b'3\r\nbar\r\n'
        )

        assert response.transport.write.call_args_list[3][0][0] == (
            b'0\r\n\r\n'
        )

        app.stop()

    streaming_app.run(host='127.0.0.1', port='23333')

