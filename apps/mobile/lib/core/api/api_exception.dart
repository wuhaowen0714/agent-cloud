class ApiException implements Exception {
  final int? status;
  final String message;
  ApiException(this.message, {this.status});
  @override
  String toString() => 'ApiException($status): $message';
}
