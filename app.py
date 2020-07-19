#!/usr/bin/env python
from threading import Lock
from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit, send, disconnect
from uuid import uuid4
import time
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'
socketio = SocketIO(app)
thread = None
thread_lock = Lock()

config_lock = Lock()
config = {
    'magnet_link': '',
    'tolerance': '2000'
}

session_lock = Lock()
session_set = set()
session_leader = None
play_status = {
    'last_update': None,
    'time': 0,
    'playing': False
}

def sync():
    while True:
        socketio.sleep(1)
        if session_leader is not None:
            with session_lock:
                socketio.emit('server_time', {'data': play_status}, broadcast=True)
        if play_status['last_update'] is not None and time.monotonic() - play_status['last_update'] > float(config['tolerance']) / 1000:
            with session_lock:
                if session_leader is not None:
                    session_set.remove(session_leader)
                leader_selection()

def leader_selection():
    global session_leader, session_set
    if len(session_set) > 0:
        app.logger.info('reselected leader')
        session_leader = random.choice(tuple(session_set))
    else:
        session_leader = None

@app.route('/')
def index():
    return render_template('index.html', async_mode=socketio.async_mode)

@socketio.on('connect')
def on_connect():
    global thread
    with thread_lock:
        if thread is None:
            thread = socketio.start_background_task(sync)

@socketio.on('start')
def on_start(message):
    global session_set, session_leader
    user_id = uuid4()
    session['user'] = user_id
    with session_lock:
        session_set.add(user_id)
        if session_leader is None:
            session_leader = user_id
            app.logger.info('selected leader')
            play_status['last_update'] = time.monotonic()
            play_status['playing'] = True
        return {'data': play_status}


@socketio.on('update')
def on_status_update(message):
    global play_status
    if 'user' not in session:
        # frontend needs to reload
        return

    with session_lock:
        playing = play_status['playing']
        if message['data']['from_event']:
            app.logger.info('new play status %s and time %s', message['data']['playing'], message['data']['time'])
            play_status = message['data']
            play_status['last_update'] = time.monotonic()
            emit('server_status', {'data': play_status}, broadcast=True)
        elif session['user'] == session_leader:
            play_status = message['data']
            play_status['last_update'] = time.monotonic()

@socketio.on('get_config')
def get_config():
    with config_lock:
        emit('server_config', {'data': config})

@socketio.on('set_config')
def set_config(message):
    global config
    with config_lock:
        config = message['data']
        emit('server_config', {'data': config}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    global session_set, session_leader
    if 'user' in session:
        with session_lock:
            user_id = session['user']
            if user_id in session_set:
                session_set.remove(user_id)
            if session_leader == user_id:
                leader_selection()

if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", debug = True)
