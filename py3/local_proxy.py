import asyncio
import struct
import traceback
import logging
import sys
import threading
import time
import copy
import argparse
import websockets

username = ''
password = ''

last_time = 0
send_load = 0
receive_load = 0

remote_host = ""
remote_port = ""

async def handle_connect_sock5(data, reader, writer):
    #Handle handshake
    log.info('Received: Handshake message')
    addr = writer.get_extra_info('peername')
    log.debug(f"Received {data!r} from {addr!r}")
    if(len(data) == 0):
        return
    reply = data[0]
    reply = bytes([reply,0x00])

    log.info("Send handshake reply to client")
    log.debug(f"Send: {reply!r} to client")
    rep = bytes(reply)
    writer.write(rep)
    await writer.drain()

    #Handle Negotiation Pass it to remote proxy with username and password
    data = await reader.read(1000)
    log.info('Received: Negotiation message from client')
    log.debug(f"Send: {data!r} from client")

    #connect to remote proxy
    rem_reader, rem_writer = await asyncio.open_connection(remote_host, remote_port)
    log.info(f'Establish connection to remoteProxy {remote_host!r} {remote_port!r}')
    #pass negotiation
    
    #pass username and password to remote proxy
    user_name = username + " "
    password_len = len(password).to_bytes(length=2,byteorder='big',signed=False)
    pass_word = " " + password
    #format:datausername len password
    neg = data + user_name.encode() + password_len + pass_word.encode()
    rem_writer.write(neg)

    #rem_writer.write(data)
    await rem_writer.drain()

    #pass reply from remotr proxy
    data = await rem_reader.read(1000)
    '''
    if(data[0] == 0x11):
        await websocket.send("Wrong info")
        return
    '''
    writer.write(data)
    await writer.drain()

    #begin delivering message between
    try:
        asyncio.gather(deliver_message(reader, rem_writer, 1), deliver_message(rem_reader, writer, -1))
    except Exception as exc:
        traceback.print_exc()
         
async def handle_connect_http(data, reader, writer):
    #extract handshake portion
    data = data.decode().split("\r\n\r\n")[0].encode()
    #Handle handshake
    log.info('Received: Handshake message')
    addr = writer.get_extra_info('peername')
    log.debug(f"Received {data!r} from {addr!r}")

    packet_list = data.decode().split(" ")
    check = packet_list[0]
    packet_list = packet_list[1:]#CONNECT
    if(check != 'CONNECT'):
        return
    
    #format:data username len password
    #change the position of \r\n\r\n
    data = data.decode().split("\r\n\r\n")[0].encode()
    user_name = " " + username + " "
    password_len = len(password).to_bytes(length=2,byteorder='big',signed=False)
    pass_word = " " + password + "\r\n\r\n"
    neg = data + user_name.encode() + password_len + pass_word.encode()

    #connect to remote proxy
    try:
        rem_reader, rem_writer = await asyncio.open_connection(remote_host, remote_port)
    except Exception as exc:
        traceback.print_exc()
    log.info(f'Establish connection to remoteProxy {remote_host!r} {remote_port!r}')
    #pass CMD
    rem_writer.write(neg);
    log.info(f"Passing negotiation {data!r} to remote_proxy")
    await rem_writer.drain()    

    #pass reply from remote proxy
    data = await rem_reader.read(1000)
    #check the authentication
    '''
    if(data == "Wrong info"):
        await websocket.send("Wrong info")
        return
    '''
    #successfully logged into remote_proxy
    writer.write(data)
    await writer.drain()

    await asyncio.gather(deliver_message(reader, rem_writer, 1), deliver_message(rem_reader, writer, -1), return_exceptions=True)

async def handle_type(reader, writer):
    data = bytes()
    try:
        data = await reader.readuntil(separator=b'\r\n\r\n')
    except asyncio.streams.IncompleteReadError as exc:
        data = await reader.read(1000)
    except asyncio.LimitOverrunError as exc:
        data = await reader.read(1000)
    except Exception as exc:
        traceback.print_exc()
    if(len(data) == 0):
        return
    if(data[0] != 0x05):
        await handle_connect_http(data, reader, writer)
    else:
        await handle_connect_sock5(data, reader, writer)

    
async def deliver_message(reader, writer, direction):
    global last_time
    global send_load
    global receive_load
    while(1):
        try:
            data = await reader.read(65535)
        except Exception as exc:
            log.info("delivering ended")
            continue
        log.debug(f'Received: {data!r}')
        if(len(data) == 0):
            addr = writer.get_extra_info('peername')
            log.info(f"Connection ended with {addr!r}")
            return
        writer.write(data)
        dest = writer.get_extra_info('peername')
        if(direction == -1):
            receive_load = receive_load + len(data)
        else:
            send_load = send_load + len(data)

        feedback = str(len(data))
        log.info(f"data len {feedback!r}")
        #websocket.send(feedback)
        log.debug(f"Send: {data!r}")
        try:
            await writer.drain()
        except Exception as exc:
            log.info("delivering ended")

def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

#
async def deal_with_socket(websocket, path):
    global username
    global password
    global send_load
    global receive_load
    global last_time
    global remote_host
    global remote_port
    recv = await websocket.recv()
    print("received : " + recv)
    #distract remote_host, remote_port, username and password
    user_pass = recv.split(" ")
    remote_host = user_pass[0]
    remote_port = user_pass[1]
    username = user_pass[2]
    password = user_pass[3]
    #start a thread
    
    coroutine1 = wait_for_request()
    new_loop = asyncio.new_event_loop()               
    t = threading.Thread(target=start_loop,args=(new_loop,))  
    t.setDaemon(True)
    t.start()
    asyncio.run_coroutine_threadsafe(coroutine1,new_loop)

    last_time = time.time()
    receive_bandwidth = 0
    send_bandwidth = 0

    while(1):
        now_time = time.time()
        if((now_time - last_time) != 0):    
            receive_bandwidth = receive_load/(now_time - last_time)
            send_bandwidth = send_load/(now_time - last_time)
            receive_load = 0
            send_load = 0
            last_time = now_time

        st = "receive: " + str(receive_bandwidth) + " " + str(send_bandwidth)
        await websocket.send(st)
        recv = await websocket.recv()
        #check if local_gui command to exit local_proxy
        await websocket.send("check")
        recv = await websocket.recv()
        if(recv == "disconnect"):
            sys.exit(0)
        time.sleep(2)

        '''
        data = await websocket.recv()
        if(data == "disconnect"):
            return
        '''
        '''
        time.sleep(1)
        st = "receive:" + str(receive_bandwith)
        #+ str(receive_bandwith)
        await websocket.send(st)
        #"send:" +  str(send_bandwith)
        await websocket.send(st)
        '''

async def wait_for_request():
    log.critical("Local proxy on service!")
    localServer = await asyncio.start_server(
        handle_type, "127.0.0.1", "8888")
    async with localServer:
        await localServer.serve_forever()

if __name__ == '__main__':
    #logging
    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)

    #argparse
    _parser = argparse.ArgumentParser(description='remote socks5 https dual proxy with authentication')
    _parser.add_argument('-d', dest='debug_level', metavar='debug_level', default = 2, help='choose debug level from 1 to 5')
    _parser.add_argument('--lh', dest='listen_host', metavar='listen_host', help='proxy listen host')
    _parser.add_argument('--lp', dest='listen_port', metavar='listen_port', help='proxy listen port')
    _parser.add_argument('--ca', dest='control_host', metavar='control_host', help='proxy control host')
    _parser.add_argument('--cp', dest='control_port', metavar='control_port', help='proxy control port')
    _parser.add_argument('--rh', dest='remote_host', metavar='remote_host',help='remote proxy listen port')
    _parser.add_argument('--rp', dest='remote_port', metavar='remote_port', help='remote proxy listen port')
    args = _parser.parse_args()
    log.info(f'{args}')

    #determin debug level
    if(args.debug_level == "1"):
            log.setLevel(logging.DEBUG)
    if(args.debug_level == "2"):
            log.setLevel(logging.INFO)
    if(args.debug_level == "3"):
            log.setLevel(logging.WARNING)
    if(args.debug_level == "4"):
            log.setLevel(logging.ERROR)
    if(args.debug_level == "5"):
            log.setLevel(logging.CRITICAL)

    if sys.platform == 'win32':
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    start_server = websockets.serve(deal_with_socket,args.control_host, args.control_port)
    log.warning("local_proxy start listening by websocket")
    asyncio.get_event_loop().run_until_complete(start_server)
    asyncio.get_event_loop().run_forever()
'''
if __name__ == '__main__':
    asyncio.run(main())
'''

#-d 3 --lh 127.0.0.1 --lp 8888 --rh 127.0.0.1 --rp 8887 --ca 127.0.0.1 --cp 8886