class ToolCall {
  final String id;
  final String name;
  final Map<String, dynamic> arguments;
  const ToolCall(
      {required this.id, required this.name, required this.arguments});

  factory ToolCall.fromJson(Map<String, dynamic> j) => ToolCall(
        id: j['id'] as String,
        name: j['name'] as String,
        arguments: (j['arguments'] as Map?)?.cast<String, dynamic>() ?? {},
      );
}

class ToolResult {
  final String callId;
  final String content;
  final bool isError;
  const ToolResult(
      {required this.callId, required this.content, required this.isError});

  factory ToolResult.fromJson(Map<String, dynamic> j) => ToolResult(
        callId: j['call_id'] as String,
        content: j['content'] as String,
        isError: j['is_error'] as bool? ?? false,
      );
}

class MessageContent {
  final String text;
  final List<String> images; // 用户随消息上传的图片(工作区相对路径)
  final List<ToolCall> toolCalls;
  final List<ToolResult> toolResults;
  final String? parentCallId; // 非空 = 子 agent 消息

  const MessageContent({
    this.text = '',
    this.images = const [],
    this.toolCalls = const [],
    this.toolResults = const [],
    this.parentCallId,
  });

  factory MessageContent.fromJson(Map<String, dynamic> j) => MessageContent(
        text: j['text'] as String? ?? '',
        images: ((j['images'] as List?) ?? const []).cast<String>(),
        toolCalls: ((j['tool_calls'] as List?) ?? const [])
            .map((e) => ToolCall.fromJson(e as Map<String, dynamic>))
            .toList(),
        toolResults: ((j['tool_results'] as List?) ?? const [])
            .map((e) => ToolResult.fromJson(e as Map<String, dynamic>))
            .toList(),
        parentCallId: j['parent_call_id'] as String?,
      );
}

class Message {
  final String id;
  final int seq;
  final String role; // user | assistant | tool
  final MessageContent content;

  const Message(
      {required this.id,
      required this.seq,
      required this.role,
      required this.content});

  factory Message.fromJson(Map<String, dynamic> j) => Message(
        id: j['id'] as String,
        seq: j['seq'] as int,
        role: j['role'] as String,
        content: MessageContent.fromJson(j['content'] as Map<String, dynamic>),
      );
}
