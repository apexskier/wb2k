# coding=utf-8

import os
import sys
import time
import logging
import logging.config

import click
import websocket  # Depedency of slackclient, needed for exception handling
from slackclient import SlackClient


def bail(msg_type, color, text):
    return "{}: {}".format(click.style(msg_type, fg=color), text)


def setup_logging(verbose):
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': "%(asctime)s [%(levelname)s] %(message)s",
                'datefmt': "[%Y-%m-%d %H:%M:%S %z]",
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
            },
        },
        'loggers': {
            '': {
                'handlers': ['console'],
                'level': logging.INFO if verbose < 1 else logging.DEBUG,
                'propagate': True,
            },
            'requests.packages.urllib3': {  # Oh, do shut up, requests.
                'handlers': ['console'],
                'level': logging.CRITICAL,
            },
        },
    })


def find_channel_id(channel, sc):
    channels_list = sc.api_call("channels.list").get('channels')
    groups_list = sc.api_call("groups.list").get('groups')

    if not channels_list and not groups_list:
        sys.exit(bail('fatal', 'red', "Couldn't enumerate channels/groups"))

    # Is there a better way to search a list of dictionaries? Probably.
    channel_ids = [c['id'] for c in channels_list + groups_list if c['name'] == channel]

    if not channel_ids:
        sys.exit(bail('fatal', 'red', "Couldn't find #{}".format(channel)))

    return channel_ids[0]


def handle_message(message, channel, channel_id, sc, logger):
    logger.debug(message)

    subtype = message.get('subtype')
    user = message.get('user')

    if subtype in ('group_join', 'channel_join') and user:
        message_channel_id = message.get('channel')
        user_profile = message.get('user_profile')
        username = user_profile.get('name')

        if message_channel_id == channel_id:
            try:
                sc.rtm_send_message(channel,
                                    "Sup, <@{}> :hand:\nMake sure to add a party hat to your avatar!".format(user))
                logger.info("Welcomed {} to #{}".format(username, channel))
            except AttributeError:
                logger.setLevel(logging.ERROR)
                logger.error("Couldn't send message to #{}".format(channel))


@click.command()
@click.option('-c', '--channel', envvar='WB2K_CHANNEL', default='general',
              show_default=True, metavar='CHANNEL',
              help='The channel to welcome users to.')
@click.option('-v', '--verbose', count=True, help='It goes to 11.')
@click.option('-r', '--retries', envvar='WB2K_RETRIES', default=8, type=(int), metavar='max_retries',
              help='The maximum number of times to attempt to reconnect on websocket connection errors')
@click.option('--announce', is_flag=True, help='Announce to the channel when started')
@click.version_option()
def cli(channel, verbose, retries, announce):

    if verbose > 11:
        sys.exit(bail('fatal', 'red', "It doesn't go beyond 11"))

    # Get our logging in order.
    logger = logging.getLogger(__name__)
    setup_logging(verbose)

    # Make sure we have an API token.
    api_token = os.environ.get('WB2K_TOKEN')
    if not api_token:
        sys.exit(bail('fatal', 'red', 'WB2K_TOKEN envvar undefined'))

    # Instantiate and connect!
    sc = SlackClient(api_token)
    if sc.rtm_connect():
        logger.info("Connected to Slack")

        channel_id = find_channel_id(channel, sc)
        logger.debug("Found channel ID {} for #{}".format(channel_id, channel))

        logger.info("Listening for joins in #{}".format(channel))

        retry_count = 0
        backoff = 0.5

        if announce:
            sc.rtm_send_message(channel, "hello party people 🎉")

        while True:
            try:
                # Handle dem messages!
                for message in sc.rtm_read():
                    handle_message(message, channel, channel_id, sc, logger)

                # Reset exponential backoff retry strategy every time we
                # successfully loop. Failure would have happened in rtm_read()
                retry_count = 0

                time.sleep(0.5)

            # The websocket module is not an explicit depedency of wb2k, but is
            # necessary to handle an error caused by a bug in Slack's python
            # client: https://github.com/slackhq/python-slackclient/issues/127
            except websocket.WebSocketConnectionClosedException:
                logger.error("Lost connection to Slack, reconnecting...")
                if not sc.rtm_connect():
                    logger.info("Failed to reconnect to Slack")
                    if retry_count >= retries:
                        sys.exit(bail(
                            'fatal',
                            'red',
                            "Too many failed reconnect attempts, shutting down")
                        )
                    time.sleep((backoff ** 2) / 4)
                else:
                    logger.info("Reconnected to Slack")

                retry_count += 1

    else:
        sys.exit(bail('fatal', 'red', "Couldn't connect to Slack"))

if __name__ == '__main__':
    cli()
