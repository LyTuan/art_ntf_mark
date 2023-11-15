import json
import time
import requests
from flask import Flask, request
from node_server import Blockchain, Block, consensus, announce_new_block
from constant import StatusCode

app = Flask(__name__)

blockchain = Blockchain()


@app.route('/new_transaction', methods=['POST'])
def new_transaction():
    tx_data = request.get_json()
    required_fields = ["author", "content"]

    for field in required_fields:
        if not tx_data.get(field):
            return "Invalid transaction data", StatusCode.NOT_FOUND

    tx_data["timestamp"] = time.time()

    blockchain.add_new_transaction(tx_data)

    return "Success", StatusCode.CREATE_SUCCESS


@app.route('/chain', methods=['GET'])
def get_chain():
    chain_data = []
    for block in blockchain.chain:
        chain_data.append(block.__dict__)

    return json.dumps({
        "length": len(chain_data),
        "chain": chain_data
    })


@app.route('/mine', methods=['GET'])
def mine_unconfirmed_transactions():
    result = blockchain.mine()
    if not result:
        return "No transactions to mine"
    return "Block #{} is mined.".format(result)


@app.route('/pending_tx')
def get_pending_tx():
    return json.dumps(blockchain.unconfirmed_transactions)


# Chứa địa chỉ host của các thành viên tham gia khác của mạng
peers = set()


# route thêm một peer mới vào mạng
@app.route('/register_node', methods=['POST'])
def register_new_peers():
    # Địa chỉ host đến các node ngang hàng
    node_address = request.get_json()["node_address"]
    if not node_address:
        return "Invalid data", 400

    # Thêm địa chỉ node vào danh sách
    peers.add(node_address)

    # Trả lại blockchain mới
    return get_chain()


@app.route('/register_with', methods=['POST'])
def register_with_existing_node():
    """
    Trong nội bộ gọi đến route `register_node` để
    đăng ký node hiện tại với node từ xa được chỉ định trong
    request và cập nhật lại mạng blockchain
    """
    node_address = request.get_json()["node_address"]
    if not node_address:
        return "Invalid data", 400

    data = {"node_address": request.host_url}
    headers = {'Content-Type': "application/json"}

    # Reuqest đăng ký với node từ xa và lấy thông tin
    response = requests.post(node_address + "/register_node",
                             data=json.dumps(data), headers=headers)

    if response.status_code == 200:
        global blockchain
        global peers
        # update chain và các peers
        chain_dump = response.json()['chain']
        blockchain = create_chain_from_dump(chain_dump)
        peers.update(response.json()['peers'])
        return "Registration successful", 200
    else:
        # Nếu có lỗi xảy ra, API sẽ trả lại response
        return response.content, response.status_code


@app.route('/mine', methods=['GET'])
def mine_unconfirmed_transactions():
    result = blockchain.mine()
    if not result:
        return "No transactions to mine"
    else:
        # Đảm bảo chúng ta có chain dài nhất trước khi thông báo với mạng
        chain_length = len(blockchain.chain)
        consensus()
        if chain_length == len(blockchain.chain):
            # thông báo block được mined gần đây vào mạng
            announce_new_block(blockchain.last_block)
        return "Block #{} is mined.".format(blockchain.last_block.index)


def create_chain_from_dump(chain_dump):
    blockchain = Blockchain()
    for idx, block_data in enumerate(chain_dump):
        block = Block(block_data["index"],
                      block_data["transactions"],
                      block_data["timestamp"],
                      block_data["previous_hash"])
        proof = block_data['hash']
        if idx > 0:
            added = blockchain.add_block(block, proof)
            if not added:
                raise Exception("The chain dump is tampered!!")
        else:  # block này là một block genesis nên không cần verification
            blockchain.chain.append(block)
    return blockchain


# Route này để thêm khối người khác vừa mined.
# Đầu tiên cần xac minh block và sau đó là thêm vào chain
@app.route('/add_block', methods=['POST'])
def verify_and_add_block():
    block_data = request.get_json()
    block = Block(block_data["index"],
                  block_data["transactions"],
                  block_data["timestamp"],
                  block_data["previous_hash"])

    proof = block_data['hash']
    added = blockchain.add_block(block, proof)

    if not added:
        return "The block was discarded by the node", 400

    return "Block added to the chain", 201


def announce_new_block(block):
    """
    Một hàm thông báo cho mạng sau khi một block đã được mined.
    Các block khác chỉ có thể xác minh PoW và thêm nó vào
    chuỗi tương ứng.
    """
    for peer in peers:
        url = "{}add_block".format(peer)
        requests.post(url, data=json.dumps(block.__dict__, sort_keys=True))
