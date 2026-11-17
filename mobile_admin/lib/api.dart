import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

/// Talks to the Django back office.
///
/// One client, held by the app shell and passed down. There is no local
/// database and no caching layer: this is a staff tool used on a phone that may
/// be shared, and an order list cached on the device outlives the session that
/// fetched it. Everything shown is fetched live or is not shown.
class Api {
  Api._();
  static final Api instance = Api._();

  static const _storage = FlutterSecureStorage();
  static const _kBase = 'base_url';
  static const _kToken = 'token';
  static const _kUser = 'username';

  String? baseUrl;
  String? _token;
  String? username;
  String? role;

  bool get isConfigured => (baseUrl ?? '').isNotEmpty;
  bool get isSignedIn => (_token ?? '').isNotEmpty;

  /// Read the saved server and token back on launch.
  Future<void> restore() async {
    baseUrl = await _storage.read(key: _kBase);
    _token = await _storage.read(key: _kToken);
    username = await _storage.read(key: _kUser);
  }

  /// Normalise whatever somebody typed into an origin this client can use.
  ///
  /// Pure and static so it can be tested without touching secure storage. The
  /// cases that actually happen: a trailing slash pasted from a browser bar, a
  /// bare hostname, and a full URL with a path on the end.
  static String normaliseBaseUrl(String value) {
    var url = value.trim();

    // Typing "mudassirllc.com" is what people actually do. Assume TLS rather
    // than silently sending a staff password over plain http.
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://$url';
    }

    // Keep the origin only. Pasting "https://mudassirllc.com/dashboard/" is a
    // natural thing to do from a browser, and without this every request would
    // go to /dashboard/api/v1/... and 404 with no clue why.
    final parsed = Uri.tryParse(url);
    if (parsed != null && parsed.host.isNotEmpty) {
      final port = parsed.hasPort ? ':${parsed.port}' : '';
      return '${parsed.scheme}://${parsed.host}$port';
    }

    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    return url;
  }

  Future<void> setBaseUrl(String value) async {
    final url = normaliseBaseUrl(value);
    baseUrl = url;
    await _storage.write(key: _kBase, value: url);
  }

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final clean = <String, String>{};
    query?.forEach((k, v) {
      if (v != null && '$v'.isNotEmpty) clean[k] = '$v';
    });
    return Uri.parse('$baseUrl/api/v1$path')
        .replace(queryParameters: clean.isEmpty ? null : clean);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (isSignedIn) 'Authorization': 'Bearer $_token',
      };

  /// Every response passes through here, so failure is described once.
  dynamic _decode(http.Response r) {
    if (r.statusCode == 204 || r.body.isEmpty) return null;
    dynamic body;
    try {
      body = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      // A proxy error page or a redirect to a login screen arrives as HTML.
      // Saying so beats "FormatException: Unexpected character".
      throw ApiException(r.statusCode,
          'The server returned a page instead of data. Check the address.');
    }
    if (r.statusCode >= 200 && r.statusCode < 300) return body;

    if (r.statusCode == 401) {
      throw ApiException(401, 'Your session has expired. Sign in again.');
    }
    if (r.statusCode == 403) {
      throw ApiException(403, _message(body) ?? 'Your account cannot do that.');
    }
    if (r.statusCode == 429) {
      throw ApiException(429, 'Too many requests. Wait a moment and retry.');
    }
    throw ApiException(r.statusCode, _message(body) ?? 'Request failed (${r.statusCode}).');
  }

  /// Pull a human sentence out of whatever shape DRF returned.
  String? _message(dynamic body) {
    if (body is Map) {
      for (final key in ['detail', 'message', 'error']) {
        if (body[key] is String) return body[key] as String;
      }
      // Field errors: {"amount": ["A valid number is required."]}
      for (final entry in body.entries) {
        final v = entry.value;
        if (v is List && v.isNotEmpty) return '${entry.key}: ${v.first}';
        if (v is String) return '${entry.key}: $v';
      }
    }
    if (body is List && body.isNotEmpty) return '${body.first}';
    return null;
  }

  Future<dynamic> _send(String method, String path,
      {Map<String, dynamic>? query, Object? body}) async {
    if (!isConfigured) throw ApiException(0, 'No server address set.');
    final uri = _uri(path, query);
    final payload = body == null ? null : jsonEncode(body);
    late http.Response r;
    try {
      switch (method) {
        case 'POST':
          r = await http.post(uri, headers: _headers, body: payload);
          break;
        case 'PATCH':
          r = await http.patch(uri, headers: _headers, body: payload);
          break;
        case 'DELETE':
          r = await http.delete(uri, headers: _headers);
          break;
        default:
          r = await http.get(uri, headers: _headers);
      }
    } catch (_) {
      throw ApiException(0, 'Cannot reach the server. Check your connection.');
    }
    return _decode(r);
  }

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _send('GET', path, query: query);
  Future<dynamic> post(String path, {Object? body}) =>
      _send('POST', path, body: body);
  Future<dynamic> patch(String path, {Object? body}) =>
      _send('PATCH', path, body: body);
  Future<dynamic> delete(String path) => _send('DELETE', path);

  /// A paginated list, flattened to its rows.
  Future<List<Map<String, dynamic>>> list(String path,
      {Map<String, dynamic>? query}) async {
    final data = await get(path, query: query);
    final rows = data is Map ? (data['results'] ?? []) : data;
    return List<Map<String, dynamic>>.from(rows as List);
  }

  // --- session ------------------------------------------------------------

  /// Sign in as staff.
  ///
  /// Deliberately the staff endpoint, not /auth/login/. That one serves
  /// customers and refuses back-office accounts outright, so pointing this app
  /// at it produces a 403 that reads like a wrong password.
  Future<void> signIn(String identifier, String password) async {
    final data = await post('/auth/staff-login/',
        body: {'email': identifier, 'password': password});
    _token = data['token'] as String;
    username = data['username'] as String?;
    role = data['role'] as String?;
    await _storage.write(key: _kToken, value: _token);
    await _storage.write(key: _kUser, value: username);
  }

  Future<void> signOut() async {
    // Best effort: revoking server-side is good hygiene, but a failure here
    // must not leave the token on the device.
    try {
      await post('/auth/logout/');
    } catch (_) {}
    _token = null;
    username = null;
    role = null;
    await _storage.delete(key: _kToken);
    await _storage.delete(key: _kUser);
  }

  // --- endpoints ----------------------------------------------------------

  Future<Map<String, dynamic>> dashboard() async =>
      Map<String, dynamic>.from(await get('/dashboard/') as Map);

  Future<Map<String, dynamic>> me() async =>
      Map<String, dynamic>.from(await get('/me/') as Map);

  Future<List<Map<String, dynamic>>> orders({String? search, String? status, int page = 1}) =>
      list('/orders/', query: {'search': search, 'status': status, 'page': page});

  Future<Map<String, dynamic>> order(int id) async =>
      Map<String, dynamic>.from(await get('/orders/$id/') as Map);

  /// Create a whole order — customer plus lines — in one request.
  ///
  /// The total is deliberately NOT sent: the server computes it from the lines.
  /// It is the figure the customer is billed, so the client asking for the
  /// order must not be the thing that decides it.
  Future<Map<String, dynamic>> createOrder(Map<String, dynamic> body) async =>
      Map<String, dynamic>.from(await post('/order-admin/', body: body) as Map);

  /// Update an order. Only the fields OrderStatusUpdateSerializer allows.
  Future<Map<String, dynamic>> updateOrder(int id, Map<String, dynamic> fields) async =>
      Map<String, dynamic>.from(await patch('/order-admin/$id/', body: fields) as Map);

  Future<List<Map<String, dynamic>>> products({String? search, int page = 1}) =>
      list('/products/', query: {'search': search, 'page': page});

  /// Products are addressed by SLUG, not id — ProductViewSet sets
  /// lookup_field = 'slug' so the customer app can use readable URLs. Passing
  /// an id here returns 404 with a message that reads like the product was
  /// deleted.
  Future<Map<String, dynamic>> product(String slug) async =>
      Map<String, dynamic>.from(await get('/products/$slug/') as Map);

  Future<Map<String, dynamic>> updateProduct(
          String slug, Map<String, dynamic> fields) async =>
      Map<String, dynamic>.from(await patch('/products/$slug/', body: fields) as Map);

  /// Create a listing. The response carries the slug, which is the only way to
  /// address the product afterwards.
  Future<Map<String, dynamic>> createProduct(Map<String, dynamic> fields) async =>
      Map<String, dynamic>.from(await post('/products/', body: fields) as Map);

  Future<List<Map<String, dynamic>>> categories() => list('/categories/');

  Future<List<Map<String, dynamic>>> tags() => list('/tags/');

  Future<Map<String, dynamic>> createTag(String name) async =>
      Map<String, dynamic>.from(await post('/tags/', body: {'name': name}) as Map);

  // --- photos and variations ----------------------------------------------

  /// Upload a photo as multipart.
  ///
  /// Not base64 in a JSON body: the phone already has the file, and encoding a
  /// 4MB camera photo inflates it by a third over a connection that may be a
  /// hotel wifi. The extension pushes base64 because it is scraping a web page
  /// and never has a file to begin with.
  Future<Map<String, dynamic>> uploadProductImage(int productId, String path) async {
    if (!isConfigured) throw ApiException(0, 'No server address set.');
    final request = http.MultipartRequest('POST', _uri('/product-images/'))
      ..fields['product'] = '$productId'
      ..files.add(await http.MultipartFile.fromPath('image', path));
    if (isSignedIn) request.headers['Authorization'] = 'Bearer $_token';

    late http.Response response;
    try {
      response = await http.Response.fromStream(await request.send());
    } catch (_) {
      throw ApiException(0, 'Upload failed. Check your connection.');
    }
    return Map<String, dynamic>.from(_decode(response) as Map);
  }

  Future<void> deleteProductImage(int id) => delete('/product-images/$id/');

  Future<List<Map<String, dynamic>>> variants(int productId) =>
      list('/product-variants/', query: {'product': productId});

  Future<Map<String, dynamic>> saveVariant(Map<String, dynamic> fields, {int? id}) async {
    final data = id == null
        ? await post('/product-variants/', body: fields)
        : await patch('/product-variants/$id/', body: fields);
    return Map<String, dynamic>.from(data as Map);
  }

  /// Retires the variation rather than erasing it — it may be on an order.
  Future<void> deleteVariant(int id) => delete('/product-variants/$id/');

  Future<List<Map<String, dynamic>>> customers({String? search, int page = 1}) =>
      list('/customers/', query: {'search': search, 'page': page});

  Future<Map<String, dynamic>> saveCustomer(Map<String, dynamic> fields, {int? id}) async {
    final data = id == null
        ? await post('/customers/', body: fields)
        : await patch('/customers/$id/', body: fields);
    return Map<String, dynamic>.from(data as Map);
  }

  Future<List<Map<String, dynamic>>> ledger({int? customerId, int page = 1}) =>
      list('/ledger/', query: {'customer': customerId, 'page': page});

  Future<Map<String, dynamic>> addLedgerEntry(Map<String, dynamic> fields) async =>
      Map<String, dynamic>.from(await post('/ledger/', body: fields) as Map);

  Future<List<Map<String, dynamic>>> tickets({String? status, int page = 1}) =>
      list('/tickets/', query: {'status': status, 'page': page});

  Future<Map<String, dynamic>> ticket(int id) async =>
      Map<String, dynamic>.from(await get('/tickets/$id/') as Map);

  Future<void> replyToTicket(int id, String body, {bool internal = false}) =>
      post('/tickets/$id/reply/', body: {'body': body, 'is_internal': internal});

  Future<Map<String, dynamic>> updateTicket(int id, Map<String, dynamic> fields) async =>
      Map<String, dynamic>.from(await patch('/tickets/$id/', body: fields) as Map);

  Future<List<Map<String, dynamic>>> productRequests({int page = 1}) =>
      list('/product-requests/', query: {'page': page});

  Future<Map<String, dynamic>> company() async =>
      Map<String, dynamic>.from(await get('/company/') as Map);
}

/// A failure with a sentence a person can act on.
class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}
