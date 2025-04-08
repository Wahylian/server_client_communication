import argparse
import socket
import threading

import API

# the amount of threads active at the moment
active_threads: int = 0

def server(host: str, port: int, delay_return: bool = False) -> None:
    """
    the logic behind the sever
    attempts to receive messages from different clients connecting to it
    and prints them to the screen
    the server is able to support multiple clients at the same time (with the power of threads and imagination!)
    :param host: the host ip
    :param port: the port to listen on
    :param delay_return: whether there will be a delay in acknowledgement on packages received from clients
    """
    global active_threads
    if delay_return:
        print("server will delay returning packages")

    #create a listening socket for the server
    #creating a tcp socket for listening
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        # sets the socket to an address that could already be in use, if the server just crushed
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # set timeout to the socket, to allow for graceful shutdown
        # if the server socket doesn't receive a connection attempt every 120 seconds it will cause a timeout
        server_socket.settimeout(120)

        # bind the socket
        server_socket.bind((host, port))

        # allow the socket to start listening to requests
        # at most allows for 5 unaccepted requests at one time
        server_socket.listen(5)

        # creating a list of threads of all connections the server has
        threads = []

        print(f"Listening on {host}:{port}")
        while True:
            # attempting to establish a connection with a user
            try:
                # creating a socket for the client and getting their ip address
                client_socket, client_address = server_socket.accept()
                # creates a thread to handle the client and add it to list of threads
                thread = threading.Thread(target=client_handler, args=(client_socket, client_address, delay_return))
                thread.start()
                threads.append(thread)

            except socket.timeout as e:
                if active_threads == 0:
                    print(f"No active clients have been on the server for the last 120 seconds.")
                    ans: str = input("would you like to shut down the server? (answer 'y' to quit)")
                    if ans.lower() == "y":
                        print("Shutdown Initiated")
                        break
            except KeyboardInterrupt:
                print("Shutdown Initiated")
                break

        # closing all the threads after all of them finish
        for thread in threads:
            thread.join()

        # closing the server's socket
        server_socket.close()

    # ends function
    return


def client_handler(client_socket: socket, client_address: tuple[str, int], is_delay:int = False) -> None:
    """
    handles a specific client connection
    :param client_socket: the socket of the client
    :param client_address: the client's address
    :param is_delay: whether there will be a delay in acknowledgement on packages received from clients
    :return:
    """
    # updates the amount of active threads
    global active_threads
    active_threads += 1
    # to pass local variables between functions and be able to access them from different functions in the same thread
    # gets the instance of the local thread
    local_thread = threading.local()

    # the client's address as a string
    client_adr = "%s:%d" % (client_address[0], client_address[1])
    local_thread.client_prefix = "{%s}" % client_adr

    with client_socket:
        print("Connection Established with %s" % client_adr)
        # the first thing the client has to send is the maximum message size they are able to send
        # and the size of their sliding window
        # to make sure that is the first thing the server receives this boolean will have to be

        # changed to true for the communication to continue
        local_thread.decided_size = False

        #sets initial max message_length
        local_thread.max_message_length = API.MESSAGE_BUFFER_SIZE

        # the size of the sliding window
        local_thread.window_size = -1

        # the last packet number to be acknowledged
        local_thread.last_acked = -1

        # the message the client sends the server
        local_thread.message = ""

        # a buffer of all un-acked packages
        local_thread.buffer = []

        while True:
            # the server needs to send the client it's maximum message size acceptance
            # the first question from the client is what size of message the server allows
            data = client_socket.recv(API.MESSAGE_BUFFER_SIZE)
            print(f"{local_thread.client_prefix} sent a request of length {len(data)} bytes")
            # if the data arrived empty the connection must have gone wrong and so the server shuts it down
            if not data:
                print(f"No data received from {local_thread.client_prefix}, closing connection")
                break
            try:
                try:
                    # if there is a delay in the processing of old messages, multiple messages could be received all at once
                    # the server knows the expected length of a message

                    # in the header of MessageHeader the first 2 bytes represent the total length of the package
                    # and so the server can read them and separate the combined packages that way
                    separated: list[bytes] = separate_requests(data)

                    # attempts to unpack the requests at separated
                    requests: list[API.MessageHeader] = []
                    for separate in separated:
                        requests.append(API.MessageHeader.unpack(separate))
                except Exception as e:
                    # if the unpacking failed for any reason
                    raise API.MessageClientError("Something went wrong while unpacking the message") from e

                # to introduce an artificial delay into the server processing time
                if is_delay:
                    API.cause_delay()

                # processing the requests from the client
                for request in requests:
                    # gets the response from the server
                    response = process_request(local_thread, request)

                # since the responses will always have the last package to be acked the server can send just the last response
                response = response.pack()
                print(f"sending response of length {len(response)} bytes to {local_thread.client_prefix}")

                client_socket.send(response)

            except Exception as e:
                # if something went wrong with the process of the response the server won't send an ack
                # which will cause the burnout timer to hit on the client side and for the packages to be resent
                print(f"Something went wrong... {e}")

        # once the communication between the client and the server ends

        # the server can now print the full message
        print_message(local_thread)

        # the socket can be closed down
        client_socket.close()

        print(f"{local_thread.client_prefix} Connection Closed")
        # once the thread finishes
        active_threads -= 1

def separate_requests(data: bytes) -> list[bytes]:
    """
    if multiple requests were received at the same time through the socket, allows to separate them into multiple requests
    :param data: the requests being combined
    :return: the requests separated
    """
    # this is the total length of the first message received (incase more than one message was received together
    total_length_of_package = API.unpack_total_message_size(data)

    if len(data) > total_length_of_package:
        separated: list[bytes] = [b""]
        counter: int = 0
        index: int = 0
        # this separates the messages received together into multiple messages
        for byte in data:
            if counter < total_length_of_package:
                separated[index] += bytes([byte])
                counter += 1
            else:
                # if the last package was separated
                # the server can now remove that message from the data
                data = data[total_length_of_package:]

                # now the server gets the size of the rest of the message
                if len(data) > 0:
                    # if the len of the data is 0 than we finished going over all the messages
                    total_length_of_package = API.unpack_total_message_size(data)

                separated.append(b"")
                index += 1
                separated[index] += bytes([byte])
                counter = 1
    else:
        separated: list[bytes] = [data]

    return separated

def buffer_request(local_thread, request: API.MessageHeader) -> None:
    """
    buffers the request into the local thread's buffer
    :param local_thread: the local thread the function is running on
    :param request: the request to buffer
    """
    # test to make sure we buffered request, will stay false if it wasn't buffered
    # happens if buffer is empty or if request comes after the last package in buffer
    buffered_request: bool = False

    request_number: int = request.package_num
    # if the request is for a package the server already acked it will not be buffered
    # since the package number is in modulo the request could have already been acked in either of the following two cases:
    # 1. last_acked - sliding_window < request_number <= last_acked (if last_acked > sliding_window)
    # 2. last_acked + sliding_window <= request_number (if last_acked < sliding_window)
    if  (local_thread.last_acked - local_thread.window_size < request_number <= local_thread.last_acked) or \
            (local_thread.last_acked + local_thread.window_size <= request_number):
        # if this is the case the package was already acked and so it can be ignored
        return

    # the request will now enter buffer in the correct placement for it
    for i in range(0, len(local_thread.buffer)):
        # going over each package in buffer
        package: API.MessageHeader = local_thread.buffer[i]

        # to enter it in the correct placement we need to place it before
        # the first package with a package number bigger than it's numbering
        package_number = package.package_num

        # before attempting to insert the request into the buffer we will check if it is already in it
        # which can happen if a timeout occurs on the client side, and they resend all the packages in their sliding window
        if request_number == package.package_num:
            buffered_request = True
            # if the request is already buffered we don't need to add it again
            break

        # since the numbering of the packages is in modulo of 2*(window_size)
        # the request is "smaller" than package if one of the following options occurs:
        # 1. if last acked is smaller than the window size
        #    then the request is smaller than package
        if 0 <= local_thread.last_acked < local_thread.window_size:
            if local_thread.last_acked < request_number < package_number:
                # if we reach this line we found the index we need to insert request in
                local_thread.buffer.insert(i, request)
                buffered_request = True
                break
        else:
            # 2. else last acked is bigger or equal to window size and smaller than 2 * (window size)
            #    if that is the case there are 3 ways for request to be "smaller" than the package
            #    a. request is bigger than last acked and smaller than package
            #    b. package is smaller than last acked which is smaller than request
            #    c. request is smaller than package which is smaller than last acked
            if (local_thread.last_acked < request_number < package_number) or (package_number < local_thread.last_acked < request_number) or\
                    (request_number < package_number < local_thread.last_acked):
                local_thread.buffer.insert(i, request)
                buffered_request = True
                break

    # if we haven't buffered request yet, we will add it to buffer
    if not buffered_request:
        local_thread.buffer += [request]

def process_request(local_thread ,request: API.MessageHeader) -> API.AckHeader:
    """
    processes the request received from the client
    :param local_thread: the local thread the function is running on
    :param request: the request to process
    :return: the ack message to send to the client
    """
    # if the server and the client haven't decided on a maximum size for a message yet the first message from the client is just a header
    if not local_thread.decided_size:
        print(f"{local_thread.client_prefix} asks for maximum size of message,\n would you like to answer through console or through file?"
              + " enter 'manual' for manual, and 'file' for reading the file that will be provided.\n"
              + f"(not case sensitive, will default to manual)")

        # the answer from the user of the server
        ans: str = input()

        # setting to the default max message length incase any other option was inputted
        max_message_length: int = API.MAX_MSG_SIZE
        if ans.lower() == "file":
            # reads the name of the file to read the instructions from
            filename: str = input("Enter filename (Case Sensitive, without extension, must be txt): ")
            # opens the file on read mode
            with open(f"{filename}.txt", "r") as file:
                # the maximum msg size is in the second line of the txt file
                # finds the line with the max message length specified in it
                file.readline()
                line = file.readline()

                # removes irrelevant information from the line
                line = line.removeprefix("maximum_msg_size:")
                line = line.removesuffix("\n")
                # converts the max message size to int
                max_message_length = int(line)
        else:
            max_message_length = int(input("Enter maximum size of message in bytes: "))

        # saves the new max message length
        local_thread.max_message_length = max_message_length
        local_thread.decided_size = True

        # saves the window size the client is using so the server knows what mod to use for buffering and saving the message
        # the window size is 1 bigger than what is actually written (read api)
        local_thread.window_size = request.window_size + 1
        # after getting the window_size we need to create 2*(window_size) lists, one at each appropriate key in message

    # added request to buffer
    buffer_request(local_thread, request)

    # after request was added to buffer in the correct place
    # all we need to do is attempt to go over buffer until the current package we are on is not the next one is sequential order

    # if the buffer is empty the request received was already acked previously, and so we will skip going over the buffer
    if len(local_thread.buffer) > 0:
        # we know buffer is not empty, it has at least 1 package, the one we just received
        for package in local_thread.buffer:
            package_number:int = package.package_num

            # if package_number is the next package numbering in sequential order after last_acked, we remove it from buffer,
            # add it to the end of the message (since it is in order) and set last_acked to package_number
            if package_number == (local_thread.last_acked+1) % (2 * local_thread.window_size):
                # remove the package from buffer
                local_thread.buffer.remove(package)

                # adds the data in package to message
                local_thread.message += API.data_to_message(package)

                # advance last_acked
                local_thread.last_acked = package_number
            else:
                # if we reached a package that is not the next one in sequential order, then we went over all the packages we can
                break

    # once we finished going over the packages we could have, we can acknowledge the last_acked package
    response = API.AckHeader(local_thread.last_acked, local_thread.max_message_length)
    return response

def print_message(local_thread) -> None:
    """
    prints the message received from the client once the entire message has been received
    :param local_thread: the local thread the function is running on
    :return:
    """
    # this function prints the message received from the client
    if local_thread.message == "":
        return

    print(f"{local_thread.client_prefix} says: '{local_thread.message}'")
    return


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Server")

    # arguments for host and port
    arg_parser.add_argument('-p','--port', type=int, default=API.SERVER_PORT, help='Port to listen on')
    arg_parser.add_argument('-H','--host', type=str, default=API.SERVER_HOST, help='Host to listen on')

    args = arg_parser.parse_args()
    host = args.host
    port = args.port

    # activating server
    server(host, port, delay_return=True)