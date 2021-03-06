import httplib2
import os
import pickle
import pytest
import socket
import sys
import tests
import time
from six.moves import urllib


@pytest.mark.skipif(
    sys.version_info <= (3,),
    reason='TODO: httplib2._convert_byte_str was defined only in python3 code version',
)
def test_convert_byte_str():
    with tests.assert_raises(TypeError):
        httplib2._convert_byte_str(4)
    assert httplib2._convert_byte_str(b'Hello') == 'Hello'
    assert httplib2._convert_byte_str('World') == 'World'


def test_reflect():
    http = httplib2.Http()
    with tests.server_reflect() as uri:
        response, content = http.request(uri + '?query', 'METHOD')
    assert response.status == 200
    host = urllib.parse.urlparse(uri).netloc
    assert content.startswith('''\
METHOD /?query HTTP/1.1\r\n\
Host: {host}\r\n'''.format(host=host).encode()), content


def test_pickle_http():
    http = httplib2.Http(cache=tests.get_cache_path())
    new_http = pickle.loads(pickle.dumps(http))

    assert tuple(sorted(new_http.__dict__)) == tuple(sorted(http.__dict__))
    assert new_http.credentials.credentials == http.credentials.credentials
    assert new_http.certificates.credentials == http.certificates.credentials
    assert new_http.cache.cache == http.cache.cache
    for key in new_http.__dict__:
        if key not in ('cache', 'certificates', 'credentials'):
            assert getattr(new_http, key) == getattr(http, key)


def test_pickle_http_with_connection():
    http = httplib2.Http()
    http.request('http://random-domain:81/', connection_type=tests.MockHTTPConnection)
    new_http = pickle.loads(pickle.dumps(http))
    assert tuple(http.connections) == ('http:random-domain:81',)
    assert new_http.connections == {}


def test_pickle_custom_request_http():
    http = httplib2.Http()
    http.request = lambda: None
    http.request.dummy_attr = 'dummy_value'
    new_http = pickle.loads(pickle.dumps(http))
    assert getattr(new_http.request, 'dummy_attr', None) is None


@pytest.mark.xfail(
    sys.version_info >= (3,),
    reason='FIXME: for unknown reason global timeout test fails in Python3 with response 200',
)
def test_timeout_global():
    def handler(request):
        time.sleep(0.5)
        return tests.http_response_bytes()

    try:
        socket.setdefaulttimeout(0.1)
    except Exception:
        pytest.skip('cannot set global socket timeout')
    try:
        http = httplib2.Http()
        http.force_exception_to_status_code = True
        with tests.server_request(handler) as uri:
            response, content = http.request(uri)
            assert response.status == 408
            assert response.reason.startswith("Request Timeout")
    finally:
        socket.setdefaulttimeout(None)


def test_timeout_individual():
    def handler(request):
        time.sleep(0.5)
        return tests.http_response_bytes()

    http = httplib2.Http(timeout=0.1)
    http.force_exception_to_status_code = True

    with tests.server_request(handler) as uri:
        response, content = http.request(uri)
        assert response.status == 408
        assert response.reason.startswith("Request Timeout")


def test_timeout_https():
    c = httplib2.HTTPSConnectionWithTimeout('localhost', 80, timeout=47)
    assert 47 == c.timeout


# @pytest.mark.xfail(
#     sys.version_info >= (3,),
#     reason='[py3] last request should open new connection, but client does not realize socket was closed by server',
# )
def test_connection_close():
    http = httplib2.Http()
    g = []

    def handler(request):
        g.append(request.number)
        return tests.http_response_bytes(proto='HTTP/1.1')

    with tests.server_request(handler, request_count=3) as uri:
        http.request(uri, 'GET')  # conn1 req1
        for c in http.connections.values():
            assert c.sock is not None
        http.request(uri, 'GET', headers={'connection': 'close'})
        time.sleep(0.7)
        http.request(uri, 'GET')  # conn2 req1
    assert g == [1, 2, 1]


def test_get_end2end_headers():
    # one end to end header
    response = {'content-type': 'application/atom+xml', 'te': 'deflate'}
    end2end = httplib2._get_end2end_headers(response)
    assert 'content-type' in end2end
    assert 'te' not in end2end
    assert 'connection' not in end2end

    # one end to end header that gets eliminated
    response = {'connection': 'content-type', 'content-type': 'application/atom+xml', 'te': 'deflate'}
    end2end = httplib2._get_end2end_headers(response)
    assert 'content-type' not in end2end
    assert 'te' not in end2end
    assert 'connection' not in end2end

    # Degenerate case of no headers
    response = {}
    end2end = httplib2._get_end2end_headers(response)
    assert len(end2end) == 0

    # Degenerate case of connection referrring to a header not passed in
    response = {'connection': 'content-type'}
    end2end = httplib2._get_end2end_headers(response)
    assert len(end2end) == 0


@pytest.mark.xfail(
    os.environ.get('TRAVIS_PYTHON_VERSION') in ('2.7', 'pypy'),
    reason='FIXME: fail on Travis py27 and pypy, works elsewhere',
)
@pytest.mark.parametrize('scheme', ('http', 'https'))
def test_ipv6(scheme):
    # Even if IPv6 isn't installed on a machine it should just raise socket.error
    uri = '{scheme}://[::1]:1/'.format(scheme=scheme)
    try:
        httplib2.Http(timeout=0.1).request(uri)
    except socket.gaierror:
        assert False, 'should get the address family right for IPv6'
    except socket.error:
        pass
