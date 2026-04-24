# tests/test_chat.py
def test_chat_without_auth(client):
    response = client.post("/api/v1/chat", json={"message": "hi"})
    # 如果加了 JWT，应返回 401
    assert response.status_code in [401, 429]  # 429 可能因限流