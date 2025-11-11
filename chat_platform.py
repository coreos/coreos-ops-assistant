from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from slack_bolt import App
import os
import logging
from nio import AsyncClient, MatrixRoom, RoomMessage, ClientConfig
from nio.store.database import SqliteStore
import asyncio
import pprint
import time
from functools import lru_cache

class ChatPlatform(ABC):
    @abstractmethod
    def send_message(self, channel: str, text: str, thread_id: Optional[str] = None):
        pass

    @abstractmethod
    def get_message(self, channel: str, event_id: str) -> str:
        pass



class SlackPlatform(ChatPlatform):
    def __init__(self, slack_bot_token: str, process_message_func):
        self.slack_app = App(token=slack_bot_token)
        self.process_message_func = process_message_func

    def send_message(self, channel: str, text: str, thread_id: Optional[str] = None):
        try:
            self.slack_app.client.chat_postMessage(channel=channel, text=text, thread_ts=thread_id)
        except Exception as e:
            logging.exception("Error sending Slack message:")

    def add_reaction(self, channel: str, name: str, timestamp: str):
        try:
            self.slack_app.client.reactions_add(channel=channel, name=name, timestamp=timestamp)
        except Exception as e:
            logging.exception("Error adding Slack reaction:")

    def remove_reaction(self, channel: str, name: str, timestamp: str):
        try:
            self.slack_app.client.reactions_remove(channel=channel, name=name, timestamp=timestamp)
        except Exception as e:
            logging.exception("Error removing Slack reaction:")

    @lru_cache(maxsize=30)
    def get_message(self, channel: str, event_id: str) -> str:
        timestamp = event_id
        result = self.slack_app.client.conversations_history(
            channel=channel,
            latest=timestamp,
            inclusive=True,
            limit=1
        )
        return result["messages"][0]["text"]

    def handle_app_mention_events(self, body, logger, say):
        logger.info(body)
        event = body["event"]
        channel = event["channel"]
        thread_id = event.get("thread_ts", None)
        event_id = event["ts"]
        self.add_reaction(channel=channel, name='hourglass_flowing_sand', timestamp=event_id)
        result = self.process_message_func(
            channel=channel,
            event_id=event_id,
            thread_id=thread_id,
            text=event["text"],
        )
        logging.info(f"Result from AI: {result}")
        say(text=result.output, thread_ts=thread_id or event_id)
        self.remove_reaction(channel=channel,
                             name='hourglass_flowing_sand',
                             timestamp=event_id)


class MatrixPlatform(ChatPlatform):
    def __init__(self, homeserver_url: str, access_token: str,
            matrix_room: str, process_message_func):
        self.starttime = int(time.time() * 1000) # current time in milliseconds
        self.homeserver_url = homeserver_url
        self.client = AsyncClient(
            homeserver=homeserver_url,
            store_path="my_matrix_store",
            config=ClientConfig(
                store_sync_tokens=True,
                store=SqliteStore
            )
        )
        self.client.access_token = access_token
        asyncio.run(self.client.whoami()) # updates user_id device_id
        self.client.user = self.client.user_id
        self.bare_username = self.client.user_id[1:].split(":")[0]
        self.matrix_room = matrix_room
        self.process_message_func = process_message_func
        response = asyncio.run(self.client.room_resolve_alias(self.matrix_room))
        self.matrix_room_id = response.room_id
        self.client.load_store()
        logging.info(f"INFO: {self.client.user_id}")

    def send_message(self, channel: str, text: str, thread_id: Optional[str] = None):
        logging.info(f"INFO: send_message channel: {channel}")
        logging.info(f"INFO: send_message thread_id: {thread_id}")
        logging.info(f"INFO: send_message text: {text}")
        try:
            content={
                "msgtype": "m.text",
                "body": text
            }
            if thread_id:
                content["m.relates_to"] = {
                    "rel_type": "m.thread",
                    "event_id": thread_id
                }
            response = asyncio.run(self.client.room_send(
                room_id=channel,
                message_type="m.room.message",
                content=content
            ))
            logging.info(f"INFO: send_message response: {response}")
        except Exception as e:
            logging.exception("Error sending Matrix message:")

    def add_reaction(self, channel: str, name: str, event_id: str):
        try:
            logging.info(f"Adding emoji {name} to {event_id} in {channel}")
            response = asyncio.run(self.client.room_send(
                room_id=channel,
                message_type="m.reaction",
                content={
                    "m.relates_to": {
                        "rel_type": "m.annotation",
                        "event_id": event_id,
                        "key": name
                    }
                }
            ))
            return response
        except Exception as e:
            logging.exception("Error sending Matrix Reaction")

    def remove_reaction(self, channel: str, event_id: str):
        try:
            logging.info(f"Removing reaction event {event_id} in {channel}")
            asyncio.run(self.client.room_redact(
                room_id=channel,
                event_id=event_id,
            ))
        except Exception as e:
            logging.exception("Error undoing Matrix Reaction")


    @lru_cache(maxsize=30)
    def get_message(self, channel: str, event_id: str) -> str:
        try:
            # Get a specific message by its matrix event ID, which
            # we've indexed as the thread_id in this program and passed
            # into this function.
            logging.info(f"Matrix: Getting message from {channel} with event_id: {event_id}")
            response = asyncio.run(self.client.room_get_event(
                self.matrix_room_id,
                event_id=event_id
            ))
            return response.event.body
        except Exception as e:
            logging.exception("Error getting Matrix message:")
            return {}

    def monitor_messages(self, room: MatrixRoom, event: RoomMessage):
        try:
            mentions = event.source.get('content', {}).get("m.mentions", {}).get("user_ids", [])
            related = event.source.get('content', {}).get('m.relates_to', {})
            if room.room_id != self.matrix_room_id \
                or event.sender == self.client.user \
                or event.server_timestamp < self.starttime \
                or self.client.user not in mentions:
                # Don't process messages that:
                #   - are not in the matrix room we are moniotring
                #   - is a message sent by this bot itself
                #   - originated before this program started
                #       - we don't want to process entire history each
                #         time we start up
                #   - doesn't mention the botuser by name
                return
            logging.info(f"INFO: got message from {room.display_name}: {event.body}")
            logging.info(pprint.pformat(event))
            event_id = event.event_id
            thread_id = None
            if related.get('rel_type', "") == 'm.thread':
                thread_id = related["event_id"]

            emoji_event = self.add_reaction(
                channel=room.room_id,
                name='⏳',
                event_id=event_id,
            )

            # Cache the calls to get_message. Otherwise there will be async calls
            # to the LLM (pydantic_ai) and async calls to Matrix (nio) happening
            # at the same time and it gets hairy.
            _ = self.get_message(channel=self.matrix_room, event_id=thread_id or event_id)
                    
            logging.info(f"INFO: room.room_id is {room.room_id}. room.display_name is {room.display_name}")
            result = self.process_message_func(
                self.matrix_room,
                event_id,
                thread_id,
                event.body
            )
            logging.info(f"Result from AI: {result}")
            self.send_message(
                text=result.output,
                channel=room.room_id,
                thread_id=thread_id or event_id,
            )

            self.remove_reaction(
                channel=room.room_id,
                event_id=emoji_event.event_id
            )

        except Exception as e:
            logging.exception(f"Error inside monitor_messages: {e}")
