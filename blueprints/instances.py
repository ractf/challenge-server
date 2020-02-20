import json
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Timer, Thread

import docker
from docker.errors import BuildError
from docker.models.containers import Container
from flask import Blueprint, request, abort, jsonify


@dataclass
class Instance:
    challenge: str
    container: Container
    port: int
    started: int
    expiry: int
    users: list
    user_limit: int

    def __repr__(self):
        return str({
            "challenge": self.challenge,
            "container": self.container,
            "port": self.port,
            "started": self.started,
            "expiry": self.expiry,
            "users": self.users,
            "user_limit": self.user_limit
        })


instances = Blueprint("instances", __name__)

ports = {}
lifetimes = {}
used_ports = []
instance_details = {}
user_instances = {}
challenge_instances = defaultdict(list)
new_instance_queue = []
user_avoid_list = defaultdict(list)
client = docker.from_env()
instance_count = 0


def container_action_log(user, challenge, container_id, action, port):
    line = jsonify({"user": user, "challenge": challenge, "container": container_id, "action": action, "port": port})


with open("challenges.json") as challenge_json:
    challenge_data = json.load(challenge_json)


def start_instance(challenge, port=None):
    if port is None:
        while True:
            port = random.randrange(1025, 65535)
            if port not in used_ports:
                break
    mem_limit = challenge_data[challenge]['mem_limit']*(1024**2)
    container = client.containers.run(challenge, detach=True, ports={ports[challenge]: port},
                                      mem_limit=mem_limit, memswap_limit=mem_limit)
    instance = Instance(challenge=challenge, container=container, port=port, started=int(time.time()),
                        expiry=int(time.time()) + lifetimes[challenge], users=[],
                        user_limit=challenge_data[challenge]['user_limit'])
    instance_details[container.short_id] = instance
    challenge_instances[challenge].append(instance)
    if instance.challenge in new_instance_queue:
        new_instance_queue.remove(instance.challenge)
    return instance


bad_challenges = []


def build_image(challenge_name):
    print("Building image for", challenge_name)
    try:
        client.images.build(path='challenges/' + challenge_name + '/', tag=challenge_name)
        ports[challenge_name] = challenge_data[challenge_name]['port']
        lifetimes[challenge_name] = challenge_data[challenge_name]['lifetime']
        if challenge_data[challenge_name]['can_prestart']:
            start_instance(challenge_name)
    except BuildError as e:
        print(f"Error building image for {challenge_name}: {str(e)}")
        bad_challenges.append(challenge_name)


for challenge_name in challenge_data:
    build_image(challenge_name)
for challenge_name in bad_challenges:
    challenge_data.pop(challenge_name)


def get_instance_for(user, challenge):
    for instance in challenge_instances[challenge]:
        if len(instance.users) < instance.user_limit and instance.container.short_id not in user_avoid_list[user]:
            if len(instance.users) + 2 > instance.user_limit:
                if challenge_data[challenge_name]['can_prestart']:
                    new_instance_queue.append(challenge)
            instance.users.append(user)
            user_instances[user] = instance
            return str(instance)
    instance = start_instance(challenge)
    instance.users.append(user)
    user_instances[user] = instance
    return instance


def cleanup():
    print("Stopping old instances...")
    for challenge in challenge_data:
        empty_containers = []
        for instance in challenge_instances[challenge]:
            if len(instance.users) == 0:
                empty_containers.append(instance)

        empty_containers.sort(key=lambda x: x.expiry, reverse=True)
        for instance in empty_containers:
            if instance.expiry < time.time():
                stop_instance(instance)
        for instance in empty_containers[:-1]:
            stop_instance(instance)

        has_free_instance = False
        for instance in challenge_instances[challenge]:
            if len(instance.users) + 2 <= instance.user_limit:
                has_free_instance = True
        if not has_free_instance and challenge not in new_instance_queue:
            new_instance_queue.append(challenge)


def prestart_instances():
    for challenge in new_instance_queue:
        print(f"Starting instance for {challenge}...")
        start_instance(challenge)


def stop_instance(instance):
    print(f"Stopping {instance.challenge}:{instance.container.short_id}...")
    instance.container.stop(timeout=5)  # TODO: can we just kill this?
    ports.pop(instance.port)
    challenge_instances['challenge'].remove(instance)
    instance_details.pop(instance.container.short_id)


@instances.route("/", methods=['POST'])
def create_instance():
    challenge = request.json.get('challenge')
    user = request.json.get('user')
    if challenge not in challenge_data:
        return abort(404)
    if user in user_instances:
        return abort(403)
    instance = get_instance_for(user, challenge)
    return str(instance)


@instances.route("/", methods=['GET'])
def list_instances():
    return str(instance_details)


@instances.route("/<string:id>", methods=['GET'])
def detail_instance(id):
    if id in instance_details:
        return str(instance_details[id])
    return abort(404)


@instances.route("/<string:id>/docker_stats", methods=['GET'])
def detail_instance(id):
    if id in instance_details:
        return str(instance_details[id].container.stats)
    return abort(404)


@instances.route("/user/<string:user>", methods=['GET'])
def user_instance(user):
    if user in user_instances:
        return str(user_instances[user])
    return abort(404)


@instances.route("/reset/<string:id>", methods=['POST'])
def request_reset(id):
    user = request.json['user']
    if user not in user_instances or id not in instance_details:
        return abort(404)
    instance = instance_details[id]
    if user not in instance.users:
        return abort(403)
    instance.users.remove(user)
    user_avoid_list[user].append(instance.container.short_id)
    new_instance = get_instance_for(user, instance.challenge)
    return str(new_instance)


@instances.route("/disconnect/<string:user>", methods=['POST'])
def disconnect(user):
    if user in user_instances:
        instance = user_instances[user]
        instance.users.remove(user)
        user_instances.pop(user)
    return "disconnected"


@instances.route("/challenges/<string:id>", methods=['DELETE'])
def delete_challenge(id):
    challenge_data.pop(id)
    return "deleted"


@instances.route("/challenges", methods=['POST'])
def add_challenge():
    name = request.json.get('name')
    port = request.json.get('port')
    lifetime = request.json.get('lifetime')
    mem_limit = request.json.get('mem_limit')
    user_limit = request.json.get('user_limit')
    can_prestart = request.json.get('can_prestart')
    if not name or not port or not lifetime or not mem_limit or not user_limit or not can_prestart:
        return abort(400)
    challenge_data[name] = request.json
    Thread(target=build_image, args=name)
    return "yes"


@instances.route("/stats", methods=['GET'])
def stats():
    return jsonify({
        "current_instances": len(instance_details),
        "total_instances": instance_count,
        "current_users": len(user_instances),
        "challenges": len(challenge_data)
    })


@instances.route("/log/<string:id>", methods=['GET'])
def get_logs(id):
    return instance_details[id].container.logs


Timer(30, cleanup).start()
Timer(5, prestart_instances).start()
