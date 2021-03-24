import asyncio
import struct
import traceback
import aiosqlite
import argparse
import logging
import sys
import copy
import time
import threading

#token bucket capacity
capacity = 100000
#mutex for operation on now_load and last_load
load_mutex = threading.Lock()
#dict for token bucket amount
now_load = dict()
#last usage time!! of token bucket
last_load_time = dict()

rate_limits = dict()

async def handle_connect_sock5(data, reader, writer):
    #handle negotiation
    log.info('Received: Negotiation message from client')
    if(data[1] != 0x01 or len(data) < 4):#Connect
        return
    #check address type
    type = data[3]#ATYP
    i = 4
    if(type == 0x01):#IPv4
        count = 4
    else:
       if(type == 0x03):#domainname
           i += 1
           count = int(data[4])#iPv6
       else:
           if(type == 0x04):
               count = 16
    #extract address
    address = ""
    address = data[i:count+i].decode()
    #extract username and password
    i += count
    port = struct.unpack("!H",data[i:i + 2])[0]
    i += 2
    authen = data[i:]
    authen_list = authen.decode().split(" ")
    username = authen_list[0]
    password_len = struct.unpack("!H",authen_list[1][0:2].encode())[0]
    password = authen_list[2][0:password_len]    
    #set up connection with remote website
    rem_reader, rem_writer = await asyncio.open_connection(address, port)
    log.info('Connecting to the remote website')

    #check information in database
    success = 0
    async with aiosqlite.connect('proxy.db') as db:
        sql_content = "SELECT password FROM users where username = \"%s\"" %username
        async with db.execute(sql_content) as cursor:
            async for row in cursor:
                if(row[0] == password):
                    log.info(f'user {row[0]} logging in')
                    load_mutex.acquire()
                    now_load[username] = 0
                    last_load_time[username] = time.time()
                    load_mutex.release()
                    success = 1
        await db.commit()

    if(not success):#Wrong password. rejection
        reply = 0x11
        log.debug(f"Send: {reply!r} to client")
        writer.write(reply.encode())
        await writer.drain()
        log.info("Wrong information!!! {username!r} {password!r}")
        return
        
    #Reply to client
    send = bytes([0x05, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    writer.write(send)
    log.debug(f"Send: {send!r} to client")
    await writer.drain()

    #begin delivering message between
    try:
        asyncio.gather(deliver_message(reader, rem_writer, username), deliver_message(rem_reader, writer, username))
    except Exception as exc:
        traceback.print_exc()

async def get_permission(len, username):
    while(1):
        load_mutex.acquire()
        now_time = time.time()
        rate = rate_limits[username]
        #compute bucket amount by computing the increase of time according to timestamp
        time_stamp = now_time-last_load_time[username]
        add_amount = time_stamp * rate * 1000
        if(now_load[username] + add_amount > capacity):
            now_load[username] = capacity
        else:
            now_load[username] = now_load[username] + add_amount
        #update last_time
        last_load_time[username] = now_time
        if(now_load[username] > len):
            log.info("message of " + str(len) + " permitted to be delivered with " + username)
            #distribute load
            now_load[username] -= len
            log.info("now load for " + username + " " + str(now_load[username]))
            load_mutex.release()
            return
        load_mutex.release()
        log.info("message of " + str(len) + " NOT!!!permitted to be delivered with " + username)
        log.info("----------------------------------------------------------------------------")
        log.info("bucket size " + str(now_load[username]))
        time.sleep(0.001)
    
async def deliver_message(reader, writer, username):
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
        feedback = str(len(data))
        log.info(f"data len {feedback!r}")
        #record load usage in now_load
        #if reaches limit reject
        await get_permission(len(data), username)

        writer.write(data)
        log.debug(f"Send: {data!r}")
        try:
            await writer.drain()
        except Exception as exc:
            log.info("delivering ended")

async def handle_connect_http(data, reader, writer):
    #extract handshake portion
    data = data.decode().split("\r\n\r\n")[0].encode()
    #Handle handshake
    log.info('Received: Negotiation message')
    addr = writer.get_extra_info('peername')
    log.debug(f"Received {data!r} from {addr!r}")
    
    packet_list = data.decode().split(" ", 2)
    check = packet_list[0]#CONNECT
    address_port = packet_list[1]#Begining from domain name
    ver = packet_list[2][5:8]#Begining from HTTP:1/1
    if(check != 'CONNECT'):
        return
    
    #extract address and port
    address_port_list = address_port.split(":")
    address = address_port_list[0]
    port = address_port_list[1]

    #extract username and password
    user_pass = data.decode().split(" ")
    username = user_pass[-3]
    password_len = struct.unpack("!H",user_pass[-2][0:2].encode())[0]
    password = user_pass[-1][0:password_len]
    log.info(f"{username!r} is trying to login")
    
    #check information in database
    success = 0
    async with aiosqlite.connect('proxy.db') as db:
        #check corresponding password of username
        sql_content = "SELECT password, limit_rate FROM users where username = \"%s\"" %username
        async with db.execute(sql_content) as cursor:
            async for row in cursor:
                if(row[0] == password):
                    log.info(f'user {username} logging in')
                    load_mutex.acquire()
                    now_load[username] = 0
                    rate_limits[username] = row[1]
                    last_load_time[username] = time.time()
                    load_mutex.release()
                    success = 1
        await db.commit()

    if(not success):#Wrong password. rejection
        reply = "Wrong info"
        log.debug(f"Send: {reply!r} to client")
        writer.write(reply.encode())
        await writer.drain()
        log.warning(f"Wrong information!!! {username!r} {password!r}")
        return

    #set up connection with remote website
    rem_reader, rem_writer = await asyncio.open_connection(address, port)
    log.info(f"Establishing connection to remote website {address!r} {port!r}")

    #reply successful connection to client
    reply = "HTTP/" + ver + " 200 " + "Connection established\r\n\r\n"
    log.debug(f"Send: {reply!r} to client")
    writer.write(reply.encode())
    await writer.drain()

    #delivering message
    await asyncio.gather(deliver_message(reader, rem_writer, username), deliver_message(rem_reader, writer, username), return_exceptions=True)

async def handle_connect(reader, writer):
    log.info("Handling connection")
    data = bytes()
    #if http message read until \r\n\r\n
    try:
        data = await reader.readuntil(separator=b'\r\n\r\n')
    except asyncio.LimitOverrunError as exc:
        #sock5 message causing overrun
        #read 1000 sock5 message
        data = await reader.read(1000)
    except Exception as exc:
        traceback.print_exc()
    if(len(data) == 0):
        return
    if(data[0] != 0x05):
        await handle_connect_http(data, reader, writer)
    else:
        await handle_connect_sock5(data, reader, writer)

async def get_rate_info(username):
    #input user rate information
    async with aiosqlite.connect('proxy.db') as db:
        sql_content = "SELECT limit_rate FROM users where username = \"%s\"" %username
        async with db.execute(sql_content) as cursor:
            async for row in cursor:
                #set dict for the load used now and load limits for certain user
                rate = row[0]
        await db.commit()
    return rate
    

async def main():
    server = await asyncio.start_server(
        handle_connect, args.listen_host, args.listen_port)
    addr = server.sockets[0].getsockname()
    log.critical(f'Serving on {addr}')
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    #logging
    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)

    #argparse
    _parser = argparse.ArgumentParser(description='local socks5 https dual proxy with authentication')
    _parser.add_argument('-d', dest='debug_level', metavar='debug_level', default = 2, help='choose debug level from 1 to 5')
    _parser.add_argument('--lh', dest='listen_host', metavar='listen_host', required=True, help='proxy listen host')
    _parser.add_argument('--lp', dest='listen_port', metavar='listen_port', required=True, help='proxy listen port')
    args = _parser.parse_args()
    log.info(f'{args}')
    #determine debug level
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

asyncio.run(main())