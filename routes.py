from flask import Blueprint, request, abort, jsonify

from challenges import Instance, start_instance, challenge_data, redis

blueprint = Blueprint('routes', __name__)


def get_instance_for(user, challenge):
    for instance_id in redis.smembers(challenge):
        instance = Instance.get(instance_id)
        if len(instance.users) < instance.user_limit and not redis.sismember(f'{user}_avoid', instance.container.id):
            if len(instance.users) + 2 > instance.user_limit:
                redis.sadd('new_instance_queue', challenge)
            instance.users.append(user)
            instance.save()
            redis.set(user, str(instance))
            return instance
    instance = start_instance(challenge)
    instance.users.append(user)
    instance.save()
    redis.set(user, str(instance))
    return instance


@blueprint.route('/', methods=['POST'])
def create_instance():
    challenge = request.json.get('challenge')
    user = str(request.json.get('user'))
    if challenge not in challenge_data:
        return abort(404)
    if redis.get(user) is not None:
        return abort(403)
    return jsonify(get_instance_for(user, challenge).to_json())


@blueprint.route('/', methods=['GET'])
def list_instances():
    return jsonify(list(redis.smembers('instance_set')))


@blueprint.route('/<string:id>', methods=['GET'])
def detail_instance(id):
    instance = Instance.get(id)
    if instance is not None:
        return jsonify(instance.to_json())
    return abort(404)


@blueprint.route('/<string:id>/docker_stats', methods=['GET'])
def docker_instance(id):
    instance = Instance.get(id)
    if instance is not None:
        return jsonify(instance.container.stats)
    return abort(404)


@blueprint.route('/user/<string:user>', methods=['GET'])
def user_instance(user):
    instance = redis.get(user)
    if instance is not None:
        return jsonify(instance)
    return abort(404)


@blueprint.route('/reset/<string:id>', methods=['POST'])
def request_reset(id):
    user = request.json['user']
    if redis.get(user) != id:
        return abort(403)
    instance = Instance.get(id)
    instance.users.remove(user)
    instance.save()
    redis.sadd(f'{user}_avoid', instance.container.id)
    new_instance = get_instance_for(user, instance.challenge)
    redis.set(user, new_instance.container_id)
    return jsonify(new_instance.to_json())


@blueprint.route('/disconnect/<string:user>', methods=['POST'])
def disconnect(user):
    instance_id = redis.get(user)
    if instance_id is not None:
        instance = Instance.get(instance_id)
        instance.users.remove(user)
        redis.delete(user)
    return 'disconnected'


@blueprint.route('/stats', methods=['GET'])
def stats():
    return jsonify({
        'current_instances': len(redis.smembers('ports')),
        'total_instances': redis.get('instances'),
        'current_users': len(redis.smembers('users')),
        'challenges': len(challenge_data)
    })


@blueprint.route('/log/<string:id>', methods=['GET'])
def get_logs(id):
    instance = Instance.get(id)
    if instance is None:
        return abort(404)
    return instance.container.logs
