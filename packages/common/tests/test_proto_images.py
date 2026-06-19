"""锁住 RunTurnRequest 携带图片路径的契约(spec: image-understanding)。"""

from agent_cloud.v1 import worker_pb2


def test_run_turn_request_carries_turn_images():
    req = worker_pb2.RunTurnRequest(
        user_message="what is in the image?",
        turn_images=["upload/a.png", "upload/b.jpg"],
    )
    parsed = worker_pb2.RunTurnRequest.FromString(req.SerializeToString())
    assert list(parsed.turn_images) == ["upload/a.png", "upload/b.jpg"]


def test_run_turn_request_turn_images_defaults_empty():
    req = worker_pb2.RunTurnRequest(user_message="hi")
    assert list(req.turn_images) == []
