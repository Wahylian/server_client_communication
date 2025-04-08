## Server-Client Communication Demonstration

---
This Project runs a basic server and client that are equipped to deal with multiple issues that may arise during their 
communication, such as:
1. Packages arriving out of order
2. Delayed ACKs from package arrival
---

### What is in the Repository
In the repository there are 3 .py files
1. [API.py](API.py) - Which is a custom API created by me for 2 different types of headers, Message Headers and ACK 
Headers.<br/> For a more in depth explanation on how to headers are built look in the ['API.py'](API.py) file.
2. [Server.py](Server.py) - A program that runs a server in which each client runs on their own thread.<br/> Allowing
for multiple clients to be taken care of at the same time.
3. [Client.py](Client.py) - A program that runs a client and can connect and communicate with the server and send it 
a message.
---

### Instructions:
* First, run the [server](Server.py) file
* After you get a message the server is listening
* Run the [client](Client.py) file and connect to the server automatically
* The program will explain the rest! :D

---

### Notes:

1. To change the Server to send ACKs with a random delay change the following setting in line #372:
```python
# Change from this:
 server(host, port, delay_return=False)
# To this:
 server(host, port, delay_return=True)
```
2. To change the Client to send Packages out of Order change the following setting in line #232:
```python
# Change from this:
  client((host, port), message, window_size, timeout, send_out_of_order=False)
# To this:
  client((host, port), message, window_size, timeout, send_out_of_order=True)
```
3. Both the server and the client allow for both a 'manual' input option and a 'read from file' input option.
The 'read from file' option needs to read from a txt file with the following format:
```text
message:”[--Enter-Your-Text-Here--]”
maximum_msg_size:[--Enter-The-Maximum-Msg-Size--]
window_size:[--Enter-The-Window-Size--]
timeout:[--Enter-The-Timeout-Time--]
``` 
&emsp; Here is an example for how the file should look with values:
```text
message:"This is a test message"
maximum_msg_size:3
window_size:4
timeout:5
```

---
 @Done By: [Wahylian](https://github.com/Wahylian)
