# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dino import environ
from dino import utils
from dino.config import ConfigKeys
from dino.utils.decorators import timeit

import logging
import traceback

__author__ = 'Oscar Eriksson <oscar.eriks@gmail.com>'

logger = logging.getLogger(__name__)


class OnMessageHooks(object):
    LAST_READ_ENABLED = None

    @staticmethod
    def last_read_enabled():
        if OnMessageHooks.LAST_READ_ENABLED is not None:
            return OnMessageHooks.LAST_READ_ENABLED

        history_type = environ.env.config.get(
                ConfigKeys.TYPE,
                domain=ConfigKeys.HISTORY,
                default=ConfigKeys.DEFAULT_HISTORY_STRATEGY)

        OnMessageHooks.LAST_READ_ENABLED = history_type == ConfigKeys.HISTORY_TYPE_UNREAD
        return OnMessageHooks.LAST_READ_ENABLED

    @staticmethod
    def do_process(arg: tuple) -> None:
        @timeit(logger, 'on_message_hooks_publish_activity')
        def publish_activity() -> None:
            user_name = activity.actor.display_name
            if utils.is_base64(user_name):
                user_name = utils.b64d(user_name)

            activity_json = utils.activity_for_message(user_id, user_name)
            environ.env.publish(activity_json)

        @timeit(logger, 'on_message_hooks_broadcast')
        def broadcast():
            room_id = activity.target.id
            if utils.user_is_invisible(user_id):
                data['actor']['attachments'] = utils.get_user_info_attachments_for(user_id)
            environ.env.send(data, json=True, room=room_id, broadcast=True)

        @timeit(logger, 'on_message_hooks_update_last_read')
        def update_last_read() -> None:
            if not OnMessageHooks.last_read_enabled():
                return

            room_id = activity.target.id
            if activity.target.object_type == 'private':
                utils.update_last_reads_private(room_id)
            else:
                utils.update_last_reads(room_id)

        @timeit(logger, 'on_message_hooks_store')
        def store() -> None:
            try:
                environ.env.storage.store_message(activity)
            except Exception as e:
                logger.error('could not store message %s because: %s' % (activity.id, str(e)))
                logger.error(str(data))
                logger.exception(traceback.format_exc())

        data, activity = arg
        user_id = activity.actor.id
        word = utils.used_blacklisted_word(activity)

        if word is None:
            broadcast()
            store()
            publish_activity()
            update_last_read()
        else:
            blacklist_activity = utils.activity_for_blacklisted_word(activity, word)
            environ.env.publish(blacklist_activity, external=True)
            environ.env.send(data, json=True, room=user_id, broadcast=False, include_self=True)

            admins_in_room = environ.env.db.get_admins_in_room(activity.target.id)
            if len(admins_in_room) > 0:
                for admin_user_id in admins_in_room:
                    environ.env.send(data, json=True, room=admin_user_id, broadcast=False, include_self=True)


@environ.env.observer.on('on_message')
def _on_message_broadcast(arg: tuple) -> None:
    OnMessageHooks.do_process(arg)
