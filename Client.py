import argparse
import random
import socket
from time import time

import API

def get_important_values() -> tuple[str, int, int]:
    """
    gets from the user a way to receive the changing data important to the client (either through manual input or through file)
    :return: values for the message, the window size and the timeout length
    """
    # before the client connects to the server the user needs to decide how they are going to enter the necessary information
    print("would you like to send message manually or with a file?\n"
          + "enter 'manual' for manual input, or 'file' for reading from the file that will be provided.\n"
          + f"(not case sensitive, if anything else is entered the client will default to 'manual')")

    # the answer from the user of the client
    ans: str = input()

    # default arguments
    message: str = ""
    window_size: int = 0
    timeout: int = 0

    if ans == 'file':
        # reads the name of the file to read the instructions from
        filename: str = input("Enter filename (Case Sensitive, without extension, must be txt): ")
        with open(f"{filename}.txt", 'r') as file:
            # the first line in file is the message
            line = file.readline()
            # removes the data not related to the message
            line = line[9:]
            line = line[:len(line)-2]
            message += line

            # the third line in the file is the window size
            file.readline()
            line = file.readline()
            # remove data not related to the window size
            line = line.removeprefix("window_size:")
            line = line.removesuffix("\n")
            window_size += int(line)

            # the fourth line in the file is the timeout length
            line = file.readline()
            line = line.removeprefix("timeout:")
            line = line.removesuffix("\n")
            timeout += int(line)
    else:
        # if the user decided to enter values manually
        message += input("message: ")
        window_size += int(input("window_size: "))
        timeout += int(input("timeout: "))

    # returns the values needed
    return message, window_size, timeout


def client(server_address: tuple[str, int], message: str, window_size: int, timeout: int, send_out_of_order: bool = False) -> None:
    """
    the logic behind the client party
    attempts to send message to server according to the provided parameters
    :param server_address: the address of the server
    :param message: the message to send to the server
    :param window_size: the window size of the client
    :param timeout: the timeout timer
    :param send_out_of_order: whether the packages will be sent to the server out of order some of the time
    """
    server_prefix = f"{{{server_address[0]}:{server_address[1]}}}"
    if send_out_of_order:
        print("sending packages out of order")
    # creates a TCP socket for the client
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        # connects the client's socket to the server
        try:
            client_socket.connect(server_address)
            print(f"{server_prefix} Connection Established")

            # the first message from the client to the server is a question about what is the maximum size of message the server is accepting
            # that question is defined as a message header with no-body in the server
            # this question will have a package number of 0
            size_request: API.MessageHeader = API.MessageHeader(total_length=None, window_size=window_size, package_num=0)

            # the client will send the packed size request to the server
            client_socket.send(size_request.pack())
            print(f"asking {server_prefix} for size limit")

            # receiving an ack from the server and with it the size the server is willing to accept
            size_response = client_socket.recv(API.ACK_BUFFER_SIZE)

            size_response = API.AckHeader.unpack(size_response)
            print(f"{server_prefix} Received Ack and size is {size_response.max_msg_size}")

            # once the client knows the maximum msg size they are able to send they can begin to send the message
            # at first we will divide message based on its length according to the max length received
            divided_msgs: list[str] = divide_msg(message, size_response.max_msg_size)

            # the numbering for the last package
            package_number = 0

            # set the socket timeout to timeout
            client_socket.settimeout(timeout)

            # the function will now create a sliding window of the size sliding window and then send the first sliding_window packages
            # to the server
            sliding_window: list[API.MessageHeader] = []

            # the client will send packages until all the parts of the message were acked
            while len(divided_msgs) > 0 or len(sliding_window) > 0:
                # only add to the sliding window if it isn't full
                if len(sliding_window) < window_size and len(divided_msgs) > 0:
                    # the number for the current package
                    package_number = (package_number + 1) % (2 * window_size)
                    # remove the first part of the message that still wasn't sent
                    # and encodes it
                    msg_part = (divided_msgs.pop(0)).encode(API.ENCODING_FORMAT)
                    # turn it into a package
                    package:API.MessageHeader = API.MessageHeader(total_length=API.MessageHeader.HEADER_MIN_LENGTH + len(msg_part), window_size=window_size, package_num=package_number, data=msg_part)

                    # add the package to the sliding window
                    sliding_window.append(package)

                    if send_out_of_order:
                        # if the packages are supposed to be sent out of order
                        # gives a one in three chance to not send a package,
                        # which will cause some package to arrive before them causing a timeout
                        # and for packages to arrive out of order
                        if random.randint(0,2) != 0:
                            print(f"sending package number {package.package_num} to {server_prefix}")
                            # send packed package to server
                            packed = package.pack()
                            client_socket.send(packed)
                    else:
                        # send packed package to server
                        print(f"sending package number {package.package_num} to {server_prefix}")
                        packed = package.pack()
                        client_socket.send(packed)
                # if the sliding window is of size 1 the client just sent the first message of the window
                if len(sliding_window) == 1:
                    first_msg_sent = time()

                # attempt to receive package from server
                # do not wait for the response since we have the timeout timer for that
                try:
                    if int(time() - first_msg_sent) > timeout:
                        # cause a manual timeout if an ack for the oldest message in the window wasn't received in time
                        raise socket.timeout
                    response = client_socket.recv(API.ACK_BUFFER_SIZE)

                    # if the response was received unpack it the client unpacks it
                    response = API.AckHeader.unpack(response)

                    # the client checks what the ack number is and removes from the window all the packages before the package that was acked (including it)
                    while len(sliding_window) > 0:
                        # before attempting to remove packages from the sliding window, the client needs to make sure the ack is for a package in it
                        # and not for a package that was acked after a timeout occurred
                        package = sliding_window[0]
                        # we check this by checking if the ack number in the response is less than a window size before the first package in the window
                        # or if the ack number in the response is more than a window size ahead of the first package
                        if (package.package_num - window_size <= response.ack_number < package.package_num) or \
                                (package.package_num + window_size <= response.ack_number):
                            # if the package that was acked has already been removed from the sliding window, break from the loop
                            break

                        package = sliding_window.pop(0)
                        if package.package_num == response.ack_number:
                            if len(sliding_window) > 0:
                                # if the sliding window is not empty the timeout clock will be compared to the first message in it
                                first_msg_sent = time()
                            # after removing the last package acked it can stop removing packages from the sliding window
                            break
                except socket.timeout as e:
                    # if a timeout occurs, reset the first_msg_sent timeout clock
                    first_msg_sent = time()

                    # if the client didn't receive a response from the server in the appropriate time
                    # if a timeout occurred, needs to resend the entire sliding window
                    for package in sliding_window:
                        print(f"sending package number {package.package_num} to {server_prefix}")
                        client_socket.send(package.pack())
        # in case the client attempts to connect the server and is unable to do so
        except Exception as e:
            print(f"{server_prefix}:{e}")


def divide_msg(message: str, max_size: int) -> list[str]:
    """
    divides the message into multiple messages compling with the limit of the maximum size of a message acceptable
    by the server
    :param message: the message to divide
    :param max_size: the maximum size each part of the message can be
    :return: a list of the messages that together create the original message, each of them have a size of at most max_size
    """
    # the function will take message and divide it to a number of messages such that each one is exactly max_size or less
    # when only the last message is less than max_size

    # the fist index
    divided_msgs: list[str] = [""]
    index: int = 0


    for char in message:
        # divided_msgs[index] needs to be smaller than max_size
        if len(divided_msgs[index]) < max_size:
            divided_msgs[index]+= char
        else:
            # if we filled a specif index in the list we advance the index by one
            index += 1
            # and we need to add a new string to the list
            divided_msgs.append(char)

    # after splitting the original message into chunks of the appropriate size, the function returns the list
    return divided_msgs

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser(description='client for server')

    # arguments for host and port
    arg_parser.add_argument("-p", "--port", type=int, default=API.SERVER_PORT, help="the port to connect to")
    arg_parser.add_argument("-H", "--host", type=str, default=API.SERVER_HOST, help="the host to connect to")

    args = arg_parser.parse_args()

    host = args.host
    port = args.port

    # important values for client to work correctly
    message, window_size, timeout = get_important_values()

    # activating client
    client((host, port), message, window_size, timeout, send_out_of_order=False)