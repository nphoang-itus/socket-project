import socket
import threading
import os
import json
import signal
import sys
import logging
import datetime

LOG_DIR = 'logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_file = os.path.join(LOG_DIR, f'server_{datetime.datetime.now().strftime('%d-%m-%Y_%Hh%Mm%Ss')}.log')
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
directory = "files"  # Thư mục chứa file
char_encoding = "utf-8"  # Bộ mã hóa ký tự

def scan_files_for_server():
    """
    Quét tất cả các file trong thư mục hiện tại, tính kích thước,
    lưu vào `data.txt` và trả về thông tin file dưới dạng dictionary.
    """
    if not os.path.exists(directory):
        logging.error(f"Error: Directory '{directory}' does not exist.")
        print(f"Error: Directory '{directory}' does not exist.")
        sys.exit(1)  # Exit the program if the directory does not exist
    
    if not os.access(directory, os.R_OK):
        logging.error(f"Error: Directory '{directory}' is not accessible.")
        print(f"Error: Directory '{directory}' is not accessible.")
        sys.exit(1)  # Exit the program if the directory is not accessible
    
    file_data = {}
    with open("data.txt", "w") as data_file:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
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
        self.file_datas = scan_files_for_server()    # Lưu thông tin file trên server
        self.is_running = True   # Biến kiểm tra server đang hoạt động hay không
        self.clients = set()  # Lưu thông tin client kết nối đến server
        self.server_socket = None  # Socket server
        self.client_threads = []    # Luồng xử lý client
        signal.signal(signal.SIGINT, self.handle_shutdown) # Xử lý tắt server khi nhận tín hiệu SIGINT
    
    def handle_shutdown(self, signum, frame):
        """
        Xử lý tắt server khi nhận tín hiệu SIGINT - Ctrl + C.
        """
        try:
            logging.info("Starting server shutdown sequence...")
            print("Server is shutting down...")
            self.is_running = False

            # Đóng tất cả kết nối đến client
            for client in self.clients.copy():
                try:
                    client.sendall(b"SERVER SHUTDOWN", encoding=char_encoding)
                    
                    logging.info(f"Closing connection to {client.getpeername()}")
                    client.close()
                except:
                    pass

            for thread in self.client_threads:
                try:
                    thread.join(timeout=2.0)
                    logging.info(f"Thread {thread.name} successfully joined")
                except Exception as e:
                    print(f"Error: {e}")
                    logging.error(f"Error: {e}")

            self.clients.clear()
            self.client_threads.clear()

            # Đóng server socket
            if self.server_socket:
                try:
                    self.server_socket.close()
                    logging.info("Server socket successfully closed")
                except Exception as e:
                    print(f"Error: {e}")
                    logging.error(f"Error: {e}")

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
        logging.info(f"New connection from {client_address}")
        print(f"New connection from {client_address}")

        try:
            # Gửi thông tin file trên server đến client
            json_data = json.dumps(self.file_datas).encode(char_encoding)
            client_connect.sendall(json_data)

            while self.is_running:
                # Nhận yêu cầu tải file từ client (format: filename|offset|size)
                request = client_connect.recv(1024).decode(char_encoding)
                if not request:
                    break

                # Xử lý yêu cầu tải file từ client
                if "|" in request:

                    filename, offset, size = request.split("|")
                    offset, size = int(offset), int(size)
                    logging.info(f'File download request from {client_address}: {filename}')

                    if filename in self.file_datas:
                        file_path = os.path.join(directory, filename)

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
            print(f"Error: {e}")

        finally:
            self.clients.remove(client_connect)
            client_connect.close()
            logging.info(f"Connection from {client_address} closed")
            print(f"Connection from {client_address} closed")

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
                print(f"Server running on {SERVER_HOST}:{SERVER_PORT}")
                print(f"Local IP address: {local_ip}")

                while self.is_running:
                    try:
                        client_connect, client_address = server.accept()
                        print(f"New connection from {client_address}")
                        logging.info(f'New connection from {client_address}') # Ghi log kết nối mới từ client

                        if self.is_running:
                            client_hanlder = threading.Thread(target=self.handle_clients, 
                                                             args=(client_connect, client_address), 
                                                             daemon=True)
                            client_hanlder.daemon = True
                            client_hanlder.start()
                            self.client_threads.append(client_hanlder)
                    except socket.timeout:
                        continue    
                    except OSError:
                        break
        except KeyboardInterrupt:
            self.handle_shutdown(signal.SIGINT, None)
            logging.info("Keyboard interrupt received")
            print("Server shutdown initiated by keyboard interrupt")
        except Exception as e:
            self.handle_shutdown(signal.SIGINT, None)
            logging.error(f"Unexpected error: {str(e)}")
            print(f"Error: {e}")
        finally:
            if self.is_running:
                self.handle_shutdown(signal.SIGINT, None)

            for handler in logging.getLogger().handlers:
                handler.flush()

if __name__ == '__main__':
    server = Server()
    server.start() # Khởi động server