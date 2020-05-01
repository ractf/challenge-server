import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

import docker
from docker.errors import BuildError
from docker.models.containers import Container
from redis import Redis

import settings

client = docker.from_env()
redis = Redis(host=settings.REDIS['ip'], port=settings.REDIS['port'], password=settings.REDIS['password'],
              db=settings.REDIS['db'], charset='utf-8', decode_responses=True)


@dataclass
class Instance:
    challenge: str
    container: Container
    port: int
    started: int
    users: list
    user_limit: int
    container_id: str

    def __str__(self):
        return json.dumps({
            "challenge": self.challenge,
            "port": self.port,
            "started": self.started,
            "users": self.users,
            "user_limit": self.user_limit,
            "container_id": self.container_id,
        })

    def to_json(self):
        return {
            "challenge": self.challenge,
            "port": self.port,
            "started": self.started,
            "users": self.users,
            "user_limit": self.user_limit,
            "container_id": self.container_id,
        }

    @classmethod
    def from_string(cls, string):
        if string is not None:
            data = json.loads(string)
            return Instance(
                challenge=data['challenge'],
                container=client.containers.get(data['container_id']),
                port=data['port'],
                started=data['started'],
                users=data['users'],
                user_limit=data['user_limit'],
                container_id=data['container_id']
            )
        return None

    @classmethod
    def get(cls, container_id):
        return Instance.from_string(redis.get(container_id))

    def save(self):
        with redis.pipeline() as pipeline:
            pipeline.set(self.container_id, str(self))
            pipeline.sadd('ports', self.port)
            pipeline.sadd(self.challenge, self.container_id)
            pipeline.sadd('instance_set', self.container_id)
            pipeline.execute()

    def stop(self):
        with redis.pipeline() as pipeline:
            pipeline.set(self.container_id, None)
            pipeline.srem('ports', self.port)
            pipeline.srem(self.challenge, self.container_id)
            pipeline.srem('instance_set', self.container_id)
            pipeline.execute()
        self.container.stop(timeout=5)


def start_instance(challenge, port=None):
    print(f'Starting {challenge}...')
    used_ports = redis.smembers('ports')
    if port is None:
        while True:
            port = random.randrange(1025, 65535)
            if port not in used_ports:
                break
    mem_limit = challenge_data[challenge]['mem_limit'] * (1024 ** 2)
    container = client.containers.run(challenge, detach=True, ports={ports[challenge]: port},
                                      mem_limit=mem_limit, memswap_limit=mem_limit)
    instance = Instance(challenge=challenge, container=container, port=port, started=int(time.time()),
                        users=[],
                        user_limit=challenge_data[challenge]['user_limit'], container_id=container.id)
    instance.save()
    redis.incr('instances')
    if redis.sismember('new_instace_queue', instance.challenge):
        redis.srem('new_instance_queue', instance.challenge)
    return instance


def build_image(challenge_name):
    print(f'Building {challenge_name}...')
    try:
        client.images.build(path=f'challenges/{challenge_name}/', tag=challenge_name)
        ports[challenge_name] = challenge_data[challenge_name]['port']
        start_instance(challenge_name)
    except BuildError as e:
        print(f"Error building image for {challenge_name}: {str(e)}")
        bad_challenges.append(challenge_name)


ports = {}
challenge_data = {}
bad_challenges = []

for file in Path('challenges').glob('*/challenge.json'):
    with file.open() as file:
        data = json.load(file)
    name = data['name']
    ports[name] = data['port']
    challenge_data[name] = data
