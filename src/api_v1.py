"""Versioned, read-only REST API for papers and discovery metadata."""

import logging
from pathlib import Path

import pymysql
from flask import Blueprint, jsonify, request, send_file

from db import get_db_connection
from paper_repository import get_paper, get_status, list_keywords, list_papers

logger = logging.getLogger(__name__)
api_v1 = Blueprint('api_v1', __name__, url_prefix='/api/v1')
_site_labels_provider = dict


def configure_api(site_labels_provider=None):
    """Configure runtime integrations without coupling the repository to app.py."""
    global _site_labels_provider
    if site_labels_provider is not None:
        _site_labels_provider = site_labels_provider
    return api_v1


def _json(payload, status=200, max_age=300):
    response = jsonify(payload)
    response.status_code = status
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['X-API-Version'] = 'v1'
    response.headers['Cache-Control'] = f'public, max-age={max_age}'
    response.add_etag()
    return response.make_conditional(request)


def _cursor():
    return get_db_connection().cursor()


def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be an integer')
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return value


@api_v1.errorhandler(ValueError)
def invalid_request(error):
    return _json({
        'error': {
            'code': 'invalid_request',
            'message': str(error),
        }
    }, status=400, max_age=0)


@api_v1.errorhandler(pymysql.Error)
def database_error(error):
    logger.exception('REST API database error')
    return _json({
        'error': {
            'code': 'service_unavailable',
            'message': 'The paper database is temporarily unavailable.',
        }
    }, status=503, max_age=0)


@api_v1.route('/')
def api_index():
    return _json({
        'name': 'arXiv++ Combinatorics API',
        'version': 'v1',
        'documentation': '/api/v1/openapi.yaml',
        'endpoints': {
            'status': '/api/v1/status',
            'papers': '/api/v1/papers',
            'paper': '/api/v1/papers/{arxiv_id}',
            'keywords': '/api/v1/keywords',
        },
    }, max_age=3600)


@api_v1.route('/status')
def status():
    cursor = _cursor()
    try:
        payload = get_status(cursor)
    finally:
        cursor.close()
    payload['documentation'] = 'https://arxiv.symmetricfunctions.com/api/v1/openapi.yaml'
    payload['mcp'] = {
        'repository_path': 'mcp_server',
        'default_api_base_url': 'https://arxiv.symmetricfunctions.com/api/v1',
    }
    return _json(payload, max_age=60)


@api_v1.route('/papers')
def papers():
    limit = _int_arg('limit', 50, 1, 100)
    cursor = _cursor()
    try:
        payload = list_papers(
            cursor,
            limit=limit,
            order=request.args.get('order', 'ingested'),
            cursor_token=request.args.get('cursor'),
            ingested_after=request.args.get('ingested_after'),
            changed_after=request.args.get('changed_after'),
            published_after=request.args.get('published_after'),
            category=request.args.get('category'),
            keyword=request.args.get('keyword'),
            query=request.args.get('q'),
            site_labels=_site_labels_provider(),
        )
    finally:
        cursor.close()
    payload['meta'] = {
        'limit': limit,
        'order': request.args.get('order', 'ingested'),
    }
    return _json(payload)


@api_v1.route('/papers/<path:arxiv_id>')
def paper(arxiv_id):
    cursor = _cursor()
    try:
        payload = get_paper(cursor, arxiv_id, _site_labels_provider())
    finally:
        cursor.close()
    if payload is None:
        return _json({
            'error': {
                'code': 'not_found',
                'message': f'No paper was found for arXiv ID {arxiv_id}.',
            }
        }, status=404, max_age=60)
    return _json({'data': payload})


@api_v1.route('/keywords')
def keywords():
    limit = _int_arg('limit', 100, 1, 500)
    cursor = _cursor()
    try:
        payload = list_keywords(
            cursor, limit=limit, site_labels=_site_labels_provider()
        )
    finally:
        cursor.close()
    return _json({'data': payload, 'meta': {'limit': limit}}, max_age=3600)


@api_v1.route('/openapi.yaml')
def openapi():
    path = Path(__file__).resolve().parents[1] / 'docs' / 'openapi-v1.yaml'
    response = send_file(path, mimetype='application/yaml')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response
