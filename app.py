import os

import docker
from flask import Flask, request, abort
from redis import Redis

import settings
import routes
from challenges import build_image

app = Flask(__name__)


@app.before_request
def check_auth():
    if 'Authorization' not in request.headers or request.headers['Authorization'] != settings.API_KEY:
        abort(403)


@app.cli.command('prestart')
def prestart():
    for challenge in os.listdir('challenges'):
        build_image(challenge)


@app.cli.command('reset')
def reset():
    redis = Redis(host=settings.REDIS['ip'], port=settings.REDIS['port'], password=settings.REDIS['password'],
                  db=settings.REDIS['db'], charset='utf-8', decode_responses=True)
    redis.flushdb()
    client = docker.from_env()
    for container in client.containers.list():
        if container.name != "cadvisor":
            print(f'Stopping {container.id}')
            container.stop(timeout=5)


app.register_blueprint(routes.blueprint, url_prefix='/')

if __name__ == '__main__':
    app.run()
