
import time
import six

import json

import threading
from websocket._abnf import ABNF
from websocket._core import WebSocket, getdefaulttimeout
from websocket._exceptions import *
import websocket._logging

class PusherWebsocket(websocket.WebSocket):
    def ping(self, payload=""):

        subscriber_message = {'event': "pusher:ping", 'data': '{}'}
        payload = json.dumps(subscriber_message)
        self.send(payload)

class PusherWebsocketApp(websocket.WebSocketApp):

    def run_forever(self, sockopt=None, sslopt=None,
                    ping_interval=0, ping_timeout=None,
                    http_proxy_host=None, http_proxy_port=None,
                    http_no_proxy=None, http_proxy_auth=None,
                    skip_utf8_validation=False,
                    host=None, origin=None, dispatcher=None):

        if not ping_timeout or ping_timeout <= 0:
            ping_timeout = None
        if ping_timeout and ping_interval and ping_interval <= ping_timeout:
            raise WebSocketException("Ensure ping_interval > ping_timeout")
        if sockopt is None:
            sockopt = []
        if sslopt is None:
            sslopt = {}
        if self.sock:
            raise WebSocketException("socket is already opened")
        thread = None
        close_frame = None
        self.keep_running = True
        self.last_ping_tm = 0
        self.last_pong_tm = 0

        def teardown():
            if thread and thread.isAlive():
                event.set()
                thread.join()
            self.keep_running = False
            self.sock.close()
            close_args = self._get_close_args(
                close_frame.data if close_frame else None)
            self._callback(self.on_close, *close_args)
            self.sock = None

        try:
            self.sock = PusherWebsocket(
                self.get_mask_key, sockopt=sockopt, sslopt=sslopt,
                fire_cont_frame=self.on_cont_message and True or False,
                skip_utf8_validation=skip_utf8_validation)
            self.sock.settimeout(getdefaulttimeout())
            self.sock.connect(
                self.url, header=self.header, cookie=self.cookie,
                http_proxy_host=http_proxy_host,
                http_proxy_port=http_proxy_port, http_no_proxy=http_no_proxy,
                http_proxy_auth=http_proxy_auth, subprotocols=self.subprotocols,
                host=host, origin=origin)
            if not dispatcher:
                dispatcher = self.create_dispatcher(ping_timeout)

            self._callback(self.on_open)

            if ping_interval:
                event = threading.Event()
                thread = threading.Thread(
                    target=self._send_ping, args=(ping_interval, event))
                thread.setDaemon(True)
                thread.start()

            def read():
                if not self.keep_running:
                    return teardown()

                op_code, frame = self.sock.recv_data_frame(True)
                if op_code == ABNF.OPCODE_CLOSE:
                    close_frame = frame
                    return teardown()
                elif op_code == ABNF.OPCODE_PING:
                    self._callback(self.on_ping, frame.data)
                elif op_code == ABNF.OPCODE_PONG or frame.data.decode("utf-8") == '{"event":"pusher:pong","data":"{}"}':
                    self.last_pong_tm = time.time()
                    self._callback(self.on_pong, frame.data)
                    pong_event = frame.data.decode("utf-8")
                    #print(f"Recieved Pong Event: {pong_event}")
                elif op_code == ABNF.OPCODE_CONT and self.on_cont_message:
                    self._callback(self.on_data, frame.data,
                                   frame.opcode, frame.fin)
                    self._callback(self.on_cont_message,
                                   frame.data, frame.fin)
                else:
                    data = frame.data
                    if six.PY3 and op_code == ABNF.OPCODE_TEXT:
                        data = data.decode("utf-8")
                    self._callback(self.on_data, data, frame.opcode, True)
                    self._callback(self.on_message, data)

                return True

            def check():
                if ping_timeout and self.last_ping_tm \
                        and time.time() - self.last_ping_tm > ping_timeout \
                        and self.last_ping_tm - self.last_pong_tm > ping_timeout:
                    raise WebSocketTimeoutException("ping/pong timed out")
                return True

            dispatcher.read(self.sock.sock, read, check)
        except (Exception, KeyboardInterrupt, SystemExit) as e:
            self._callback(self.on_error, e)
            if isinstance(e, SystemExit):
                # propagate SystemExit further
                raise
            teardown()
