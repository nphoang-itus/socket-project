import socket
import threading
import os
import json
import signal
import sys
import logging
import datetime
import struct
import time

LOG_DIRECTORY = 'logs'
if not os.path.exists(LOG_DIRECTORY):
    os.makedirs(LOG_DIRECTORY)

log_file = os.path.join(LOG_DIRECTORY, f'server_{datetime.datetime.now().strftime('%d-%m-%Y_%Hh%Mm%Ss')}.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# Cấu hình mạng
SERVER_HOST = '0.0.0.0'
SERVER_PORT = 6264
SERVER_FILES_DIRECTORY = "server_files"  # Thư mục chứa file
CHAR_ENCODING = "utf-8"  # Bộ mã hóa ký tự
METADATA_FILE = "data.txt"

def scan_available_files():
    """
    Quét tất cả các file trong thư mục hiện tại, tính kích thước,
    lưu vào `data.txt` và trả về thông tin file dưới dạng dictionary.
    """
    if not os.path.exists(SERVER_FILES_DIRECTORY):
        logging.error(f"Error: Directory '{SERVER_FILES_DIRECTORY}' does not exist.")
        sys.exit(1)  # Exit the program if the directory does not exist
    
    if not os.access(SERVER_FILES_DIRECTORY, os.R_OK):
        logging.error(f"Error: Directory '{SERVER_FILES_DIRECTORY}' is not accessible.")
        sys.exit(1)  # Exit the program if the directory is not accessible
    
    file_data = {}
    with open(METADATA_FILE, "w") as data_file:
        for filename in os.listdir(SERVER_FILES_DIRECTORY):
            file_path = os.path.join(SERVER_FILES_DIRECTORY, filename)
            if os.path.isfile(file_path):
                size_bytes = os.path.getsize(file_path)
                size_readable = convert_size(size_bytes)
                file_data[filename] = size_bytes    
                data_file.write(f"{filename} {size_readable}\n")
    return file_data

def convert_size(size_bytes):
    """
    Chuyển đổi kích thước file từ bytes sang KB, MB, hoặc GB phù hợp.
    """
    if size_bytes >= 1024 ** 4:
        return f"{size_bytes / (1024 ** 4):.2f}TB"
    elif size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f}GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.2f}MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f}KB"
    else:
        return f"{size_bytes}B"

class Server:
    """
    Server xử lý đa luồng cho phép client tải file theo từng chunk.
    """
    def __init__(self):
        self.file_data = scan_available_files()    # Lưu thông tin file trên server
        self.is_running = True   # Biến kiểm tra server đang hoạt động hay không
        self.clients = set()  # Lưu thông tin client kết nối đến server
        self.server_socket = None  # Socket server
        self.client_threads = []    # Luồng xử lý client
        self.finished_threads = [] # Luồng đã kết thúc
        signal.signal(signal.SIGINT, self.handle_shutdown) # Xử lý tắt server khi nhận tín hiệu SIGINT
    
    def handle_shutdown(self, signum, frame):
        """
        Xử lý tắt server khi nhận tín hiệu SIGINT - Ctrl + C.
        """
        try:
            logging.info("Starting server shutdown sequence...")
            self.is_running = False

            # Đóng tất cả kết nối đến client
            for client in self.clients.copy():
                try:
                    # Kiểm tra socket còn mở trước khi gửi thông báo
                    if client.fileno() != -1:  
                        logging.info(f"Closing connection to {client.getpeername()}")
                        message = (f"SERVER_SHUTDOWN").encode(CHAR_ENCODING)
                        client.sendall(message)
                        time.sleep(3)
                    client.close()
                except Exception as e:
                    logging.error(f"Error while closing client socket: {e}")

                
            for thread in self.client_threads:
                try:
                    thread.join(timeout=2.0)
                    logging.info(f"Thread {thread.name} successfully joined")
                except Exception as e:
                    logging.error(f"Error: {e}")

            self.clients.clear()
            self.client_threads.clear()

            # Đóng server socket
            if self.server_socket and self.server_socket.fileno() != -1:
                try:
                    self.server_socket.close()
                    logging.info("Server socket successfully closed")
                except Exception as e:
                    logging.error(f"Error: {e}")
                finally:
                    self.server_socket = None

            for handler in logging.getLogger().handlers:
                handler.flush()
                handler.close()

        except Exception as e:
            logging.critical(f'Unexpected error during shutdown: {str(e)}')
            raise
                
    
    def handle_clients(self, client_connect, client_address):
        """
        Xử lý client kết nối đến server.
        """
        self.clients.add(client_connect)

        try:
            # Gửi thông tin file trên server đến client
            json_data = json.dumps(self.file_data).encode(CHAR_ENCODING)
            
            # Định dạng độ dài (4 bytes unsigned int)
            header = struct.pack(">Q", len(json_data))

            # Gửi header trước, sau đó là payload
            client_connect.sendall(header + json_data)

            while self.is_running:
                # Nhận yêu cầu tải file từ client (format: filename|offset|size)
                size_request = client_connect.recv(8)

                if not size_request:
                    break

                size_request = struct.unpack(">Q", size_request)[0]
                request = client_connect.recv(size_request).decode(CHAR_ENCODING)
                if not request:
                    break
                
                if "CLOSE PART SOCKET" in request:
                    logging.info(f'Message: "{request}" from {client_address}')
                    break

                # Xử lý yêu cầu tải file từ client
                if "|" in request:

                    filename, offset, size = request.split("|")
                    offset, size = int(offset), int(size)
                    logging.info(f'File download request from {client_address}: {filename}')

                    if filename in self.file_data:
                        file_path = os.path.join(SERVER_FILES_DIRECTORY, filename)

                        if os.path.exists(file_path) and os.path.isfile(file_path):
                            with open(file_path, "rb") as file:
                                file.seek(offset)
                                part_file_data = file.read(size)
                                client_connect.sendall(part_file_data)
                            logging.info(f"File chunk sent to {client_address}")
                        
                        else:
                            client_connect.sendall(b"ERROR: File not found on server!")

        except Exception as e:
            logging.error(f"Error: {e}")

        finally:
            if client_connect in self.clients:
                self.clients.remove(client_connect)
            try:
                if client_connect.fileno() != -1:
                    client_connect.close()
            except Exception as e:
                logging.error(f"Error while closing client connection: {e}")
            logging.info(f"Connection from {client_address} closed")



    def start(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                self.server_socket = server
                server.bind((SERVER_HOST, SERVER_PORT))
                server.listen()
                server.settimeout(1)

                local_ip = socket.gethostbyname(socket.gethostname())
                logging.info(f'Server running on {SERVER_HOST}:{SERVER_PORT}') # Ghi log server đang chạy
                logging.info(f'Local IP address: {local_ip}') # Ghi log địa chỉ IP local

                while self.is_running:
                    try:
                        client_connect, client_address = server.accept()
                        logging.info(f'New connection from {client_address}') # Ghi log kết nối mới từ client

                        if self.is_running:
                            client_handle = threading.Thread(target=self.handle_clients, 
                                                             args=(client_connect, client_address), 
                                                             daemon=True)
                            client_handle.start()
                            self.client_threads.append(client_handle)
                    except socket.timeout:
                        continue    
                    except OSError:
                        break
        except KeyboardInterrupt:
            self.handle_shutdown(signal.SIGINT, None)
            logging.info("Keyboard interrupt received")
        except Exception as e:
            self.handle_shutdown(signal.SIGINT, None)
            logging.error(f"Unexpected error: {str(e)}")
        finally:
            if self.is_running:
                self.handle_shutdown(signal.SIGINT, None)

            for handler in logging.getLogger().handlers:
                handler.flush()

if __name__ == '__main__':
    server = Server()
    server.start() # Khởi động server