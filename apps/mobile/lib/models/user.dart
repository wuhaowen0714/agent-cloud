class User {
  final String id;
  final String email;
  const User({required this.id, required this.email});

  factory User.fromJson(Map<String, dynamic> j) =>
      User(id: j['id'] as String, email: j['email'] as String);
}
