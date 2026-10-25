"""The access log keeps the path, never the query string (what people search for)."""

import logging

import uvicorn

from arestoteles import main


def test_access_log_drops_the_query():
    uvicorn.Config(app=lambda scope, receive, send: None, log_level="info")  # sets up uvicorn's loggers, as at start
    main.quiet_access_log()
    main.quiet_access_log()  # a second call adds nothing
    access = logging.getLogger("uvicorn.access")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    access.addHandler(handler)
    try:
        access.info('%s - "%s %s HTTP/%s" %d', "192.0.2.1:0", "GET", "/api/arestoteles/search?q=Garching&limit=5", "1.1", 200)
        access.info('%s - "%s %s HTTP/%s" %d', "192.0.2.1:0", "GET", "/api/arestoteles/search", "1.1", 401)
    finally:
        access.removeHandler(handler)
        for f in [f for f in access.filters if type(f).__name__ == "_NoQueryInAccessLog"]:
            access.removeFilter(f)
    assert [r.getMessage() for r in records] == [
        '192.0.2.1:0 - "GET /api/arestoteles/search HTTP/1.1" 200',
        '192.0.2.1:0 - "GET /api/arestoteles/search HTTP/1.1" 401',
    ]
