from challenges import challenge_data, Instance, start_instance, redis


def cleanup():
    print("Stopping old instances...")
    for challenge in challenge_data:
        empty_containers = []
        has_free_instance = False

        for instance_id in redis.smembers(challenge):
            instance = Instance.get(instance_id)
            if len(instance.users) + 2 <= instance.user_limit:
                has_free_instance = True
            elif len(instance.users) == 0:
                empty_containers.append(instance)

        empty_containers.sort(key=lambda x: x.started)
        for instance in empty_containers[:-1]:
            instance.stop()

        if not has_free_instance and not redis.sismember('new_instance_queue', challenge):
            redis.sadd('new_instance_queue', challenge)


def prestart_instances():
    for challenge in redis.smembers('new_instance_queue'):
        print(f"Starting instance for {challenge}...")
        start_instance(challenge)
