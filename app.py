import os

from flask import Flask, request, abort

from blueprints import instances

app = Flask(__name__)
api_key = os.getenv("API_KEY")


@app.before_request
def check_auth():
    if 'Authorization' not in request.headers or request.headers['Authorization'] != api_key:
        abort(403)


app.register_blueprint(instances.instances, url_prefix='/instances/')

if __name__ == '__main__':
    app.run()
