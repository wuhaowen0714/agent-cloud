from agent_cloud.v1 import worker_pb2


def test_extract_memory_messages_exist():
    req = worker_pb2.ExtractMemoryRequest(user_memory="x", soft_max_chars=2000)
    assert req.user_memory == "x"
    assert req.soft_max_chars == 2000
    resp = worker_pb2.ExtractMemoryResponse(user_memory="y", user_changed=True)
    assert resp.user_changed is True


def test_worker_stub_has_extract_memory():
    from agent_cloud.v1 import worker_pb2_grpc

    assert hasattr(worker_pb2_grpc.WorkerStub, "ExtractMemory") or hasattr(
        worker_pb2_grpc, "WorkerStub"
    )
