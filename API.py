import typing
import struct
import warnings
import pickle
import time
import random

SERVER_HOST: str = "127.0.0.1"
SERVER_PORT: int = 8080
# the size of a message is at most 2**16-1 bytes and so that is the size of it's buffer
MESSAGE_BUFFER_SIZE: int = 2**16-1
# the size of the ack is always exactly 3 bytes, so that is the size of it's buffer
ACK_BUFFER_SIZE: int = 3
#the maximum size of the message the client can send to the server without the header is 2**16-5
MAX_MSG_SIZE: int = 2**16-5

ENCODING_FORMAT: str = "utf-8"

"""

A message from the client includes the following data:
        
1.  the total length of the current package (the amount of bytes with actual meaning [includes the header]):
    the size of the current message can be at most the maximum message size the client can send,
    we will limit it to 16 bits.
    this means that the client can send a message of at most 2**16-1 == 65535 bytes of information
    this is equal to 2 bytes, and will be represented by an unsigned short -> H
    
2.  the maximum message size the client sends:
    this will be at most 4 bytes smaller than the maximum total length of the package
    since the header is 4 bytes of data and the actual message will be the rest of it
    this means that the client can send a message of at most 2**16-5 = 65531 bytes of information
    this is equal to 2 bytes, and will be represented by an unsigned short -> H
    
3.  the size of the sliding window they have:
    this is the amount of packages the client can send the server at any one time, before receiving 
    acknowledgements for them.
    we will limit it to 7 bits, so at most the sliding window size will be 128 (in this case 0 represents 1 and so on)  
    (we start at 1 because it makes no sense for a sliding window to be of size 0)
    this is equal to 1 bytes, an will be represented by an unsigned char -> B
    [the last bit will have no meaning in this case, as to not have a problem with the packege numbering]
    
4.  the numbering of the packege
    the numbering of the package can be from 0 to 2*n-1, where n is the size of the sliding window
    and so it will take twice the number of bits as the sliding window, so 8 bits
    this is equal to 1 bytes, an will be represented by an unsigned char -> B

5.  the data of the message
    the rest of the message is equal to the size of the current message - the size of the header 
    since at most the maximum message size in bytes is 65535 bytes (as specified above), and the header size is 4 bytes
    the maximum amount of data is 65531 bytes
    
a diagram of the package:    
 
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 
|                               |                               |
|         total length          |         max msg size          |
|---------------+---------------|-------------------------------|
|               |              X|                               |
|  window size  |  package num  |                               |            
|---------------|---------------|                               |
|                                                               | 
|                                                               |
|                                                               |
|                            DATA                               |
|                                                               |
|                                                               |
|_______________________________________________________________|


The Header format will there for be '!HHBB'
since the package is read with big endian used for networks -> '!'
total length, up to 2**16-1, represented using 2 bytes -> H
maximum size of message, up to 2**16-5, represented using 2 bytes -> H
sliding window size, up to 2**7, represented using 7 bits, so 1 byte -> B
package numbering, up to 2**8-1, represented using 1 byte -> B 


***note***
on the first message from the client to the server they will send a MessageHeader that has only the header in it
the max msg size will be HEADER_MIN_LENGTH
this will signify the server that this is a request for the size of message it is willing to accept
"""



class MessageHeader:
    """
    A class to represent a message header
    from the client to the server
    """
    # header format explained above
    HEADER_FORMAT: typing.Final[str] = '!HHBB'
    # struct calcsize calculates the minimum size of the header based on the format - also explained above
    HEADER_MIN_LENGTH: typing.Final[int] = struct.calcsize(HEADER_FORMAT)

    # the following constants are the top limits for the packages based on the actual amount of bits of data used

    # the maximum length of the package can be 2**16-1 bytes, as explained in the format of the header
    DEFAULT_HEADER_MAX_LENGTH: typing.Final[int] = 2**16-1
    # the biggest size a sliding window can be is 128
    DEFAULT_MAX_WINDOW_SIZE: typing.Final[int] = 2**7
    #the maximum length of the actual message can be 2**16-5 bytes, as explained in the format of the header
    DEFAULT_MAX_MSG_SIZE: typing.Final[int] = DEFAULT_HEADER_MAX_LENGTH - 4


    # the constructor for a message header
    def __init__(self, total_length: typing.Optional[int], window_size: int, package_num: int, max_msg_size: int = -1,data: bytes = b'') -> None:
        """
        class constructor
        """
        self.total_length = total_length
        # if the total length of the message is not provided the api can calculate it itself
        if self.total_length is None:
            self.total_length = self.HEADER_MIN_LENGTH + len(data)
        # else if there is a discrepancy between the expected total length of the message and the provided length
        elif self.total_length != self.HEADER_MIN_LENGTH + len(data):
            # fixes the discrepancy by changing total_length to the appropriate length and adds a warning
            self.total_length = self.HEADER_MIN_LENGTH + len(data)
            # this will not throw an error since there is a default max size and the error is fixable
            warnings.warn(f'for next time, please provide the correct total length')

        # if the max_msg_size is smaller or equal to the default max msg size the api will save it
        # the max msg size has to bigger than 0 to actually pass any messages
        if self.DEFAULT_MAX_MSG_SIZE >= max_msg_size > 0:
            self.max_msg_size = max_msg_size
        # else the package will use the default max size
        else:
            self.max_msg_size = self.DEFAULT_MAX_MSG_SIZE

        # if the total length of the message is not within the parameters provided throws an error
        if not (self.HEADER_MIN_LENGTH <= self.total_length <= self.max_msg_size):
            raise ValueError(f'invalid total length, expected a number between {self.HEADER_MIN_LENGTH} and {self.max_msg_size}, '
                             f'instead got {self.total_length}')

        # the api makes sure the window size will fit inside the package
        if window_size < 1 or window_size > self.DEFAULT_MAX_WINDOW_SIZE:
            raise ValueError(f'invalid window size, expected a number between 1 and {self.DEFAULT_MAX_WINDOW_SIZE}, '
                             f'instead got {window_size}')
        else:
            # since the window size takes 7 bits, the api removes 1 from the size, and adds 1 later
            self.actual_window_size = window_size
            self.window_size = window_size-1

        # the numbering for packages sent from a sliding window of size n is between 0 and 2n (excluding 2n)
        max_package_num: int = 2*(self.actual_window_size)
        if package_num < 0 or package_num >= max_package_num:
            raise ValueError(f'invalid package number, expected a number between 0 and {max_package_num} (excluding)')
        else:
            self.package_num = package_num

        # the maximum amount of data that can be sent is no longer the default amount
        max_data_size: int = self.max_msg_size - self.HEADER_MIN_LENGTH

        # the size of the data cannot be bigger than the maximum data length
        self.data = data
        if len(self.data) > max_data_size:
            raise ValueError(f'invalid data size, expected at most {max_data_size}, instead got {len(self.data)}')

    def __repr__(self) -> str:
        """
        an unambiguous representation of the package
        :return: a string representation of the package
        """
        # returns an unambiguous representation of the package
        string: str = f'{self.__class__.__name__}: '
        string += f'total_length={self.total_length}, max_msg_size={self.max_msg_size}, '
        string += f'window_size={self.actual_window_size}, package_num={self.package_num}, '
        string += f'data(in binary)=\'{self.data}\''
        return string

    def __str__(self) -> str:
        """
        a readable string representation of the package
        :return: a string representation of the package
        """
        # returns a readable representation of the package
        string:str = f"package number: {self.package_num}\nsize of message: {self.total_length}\nmaximum size of message: {self.max_msg_size}\n"
        if self.total_length > self.HEADER_MIN_LENGTH:
            string += f"the message sent in the package: {data_to_message(self)}"
        else:
            string += f"the message sent no data"
        return string

    def pack(self) -> bytes:
        """
        packs the package into bytes, according to the header format
        :return: the package in byte form
        """
        # packs the relevant values of the package into byte format and adds the data which is also it byte form
        # the header format is sent so the packer knows how to pack the relevant information according to the format
        return struct.pack(self.HEADER_FORMAT, self.total_length, self.max_msg_size, self.window_size, self.package_num) + self.data

    @classmethod
    def unpack(cls, data: bytes) -> 'MessageHeader':
        """
        unpacks the package from bytes form, into a MessageHeader
        :param data: the data that represents a MessageHeader in byte form
        :return: a MessageHeader
        """
        # handles unusable data
        if len(data) < cls.HEADER_MIN_LENGTH:
            raise ValueError("data is too short to be a header")
        # cls.HEADER_FORMAT specifies the format into which the message needs to be unpacked
        # data[:cls.HEADER_MIN_LENGTH] tells the function which part of the data needs to be unpacked
        total_length, max_msg_size, window_size, package_num = struct.unpack(cls.HEADER_FORMAT, data[:cls.HEADER_MIN_LENGTH])

        # creates an object of the MessageHeader class that contains the data that was unpacked
        # the data of the message is the rest of the data provided that wasn't unpacked
        return cls(total_length=total_length, window_size=window_size+1, package_num=package_num, max_msg_size=max_msg_size, data=data[cls.HEADER_MIN_LENGTH:])

    def __bytes__(self) -> bytes:
        """
        :return: a byte representation of the package
        """
        # returns a representation of the object in bytes
        return self.pack()

def data_to_message(header: MessageHeader) -> str:
    """
    separates the data in the message and decodes it
    :param header: the package
    :return: decoded message
    """
    # attempts to decode the message
    try:
        # decodes the message based on the format utf-8
        message_str = header.data.decode(ENCODING_FORMAT)
        if not isinstance(message_str, str):
            raise ValueError(f'invalid data type, expected a string but got {type(message_str)}')
    # there are two reasons the unpickling can fail
    except pickle.UnpicklingError as e:
        # if the data couldn't deserialize
        # sets the cause of the exception as e
        raise ValueError('data couldn\'t be deserialized') from e
    except Exception as e:
        # of if the that wasn't a message that could be translated
        # sets the cause of the exception as e
        raise ValueError('the data wasn\'t a message') from e

    # if no errors are thrown returns the message
    return message_str


def unpack_total_message_size(data: bytes) -> int:
    """
    unpacks the total message size from the package according to the header format
    and translate it into usable form
    :param data: a MessageHeader in byte form
    :return: the total size of the message
    """
    if len(data) < MessageHeader.HEADER_MIN_LENGTH:
        raise ValueError('data too short to be a header')
    # the first two bytes of a MessageHeader are the total length of the message
    # since the api knows the format of the header it can know which part of the data to unpack and in what format
    total_length: int = struct.unpack("!H", data[:2])[0]
    return total_length

class MessageClientError(Exception):
    # an exception if the message the client sent caused an exception
    pass


"""

a message from the server to the client will hold the following information:

1.  the size of package the server is willing the accept
    since the maximum package size the client can send is 2**16 bits, this will be the limit for the server's acceptance
    this is equal to 2 bytes, an will be represented by an unsigned short -> H

2.  the numbering of the acknowledgment (ack number)
    the range of this number will vary but it will be dependent on the package numberings received from the client
    those will go between 0 and 2*n-1 where n is the size of the sliding window
    though at most n could be equal to 2**7 and so the size of this field is 8 bits
    this is equal to 1 bytes, an will be represented by an unsigned char -> B
    
a diagram of the ack:

 0                   1                   2
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 
|                                   |           |
|           max msg size            |  ack num  |
|___________________________________|___________|

The Header format will there for be '!HB'
since the package is read with big endian used for networks -> '!'
total length, up to 2**16, represented using 2 bytes -> H
package numbering, up to 2**8-1, represented using 1 byte -> B 

"""

class AckHeader:
    # header format explained above
    HEADER_FORMAT: typing.Final[str] = '!HB'
    # struct calcsize calculates the size of the header based on the format - also explained above
    HEADER_LENGTH: typing.Final[int] = struct.calcsize(HEADER_FORMAT)

    # the constructor for ack header
    def __init__(self, ack_number: int, max_msg_size: int = -1):
        """
        class constructor
        """
        # the max msg size needs to be a number between 0 and 2**16-1,
        if max_msg_size < 0 or max_msg_size >= 2**16:
            raise ValueError(f'invalid ack number, expected a number between 0 and {2**16-1}, instead got {max_msg_size}')
        else:
            self.max_msg_size = max_msg_size

        # the ack numbering can be any number between 0 and 2**8-1
        if ack_number < 0 or ack_number >= 2**8:
            raise ValueError(f'invalid ack number')
        else:
            self.ack_number = ack_number

    def __repr__(self) -> str:
        """
        an unambiguous representation of the ack package
        :return: a string representation of the ack package
        """
        # returns an unambiguous representation of the ack
        string: str = f'{self.__class__.__name__}: '
        string += f'max_msg_size={self.max_msg_size}, '
        string += f'ack number: {self.ack_number}'
        return string

    def __str__(self) -> str:
        """
        a readable string representation of the ack package
        :return: a string representation of the ack package
        """
        # returns a readable version of the package
        string: str = f'ack #{self.ack_number}\n maximum size of message: {self.max_msg_size}'
        return string

    def pack(self) -> bytes:
        """
        packs the ack package into bytes, according to the header format
        :return: the ack package in byte form
        """
        # packs the ack into byte form
        return struct.pack(self.HEADER_FORMAT, self.max_msg_size, self.ack_number)

    @classmethod
    def unpack(cls, data: bytes) -> 'AckHeader':
        """
        unpacks the ack package from bytes form, into an AckHeader
        :param data: the data that represents a AckHeader in byte form
        :return: an AckHeader
        """
        # handles unusable data
        if len(data) != cls.HEADER_LENGTH:
            raise ValueError("data is not the correct length")

        # cls.HEADER_FORMAT specifies the format into which the message needs to be unpacked
        # data[:cls.HEADER_MIN_LENGTH] tells the function which part of the data needs to be unpacked
        max_msg_size, ack_number = struct.unpack(cls.HEADER_FORMAT, data[:cls.HEADER_LENGTH])

        # creates an object of the AckHeader class that contains the data that was unpacked
        return cls(max_msg_size=max_msg_size, ack_number=ack_number)

    def __bytes__(self) -> bytes:
        # returns a representation of the object in bytes
        return self.pack()


class AckServerError(Exception):
    # an exception if the ack the server sent caused an exception
    pass


def cause_delay():
    """
    causes a random amount of delay between 1 and 10 seconds, has a chance of 1/3 to happen
    """
    # the delay has a 1 in 3 chance to happen
    if random.randint(0, 3) == 0:
        # the delay will be a random time between 1 and 10 seconds
        delay_time: int = random.randint(1, 10)
        print(f"a delay of {delay_time} seconds has occurred")
        time.sleep(delay_time)