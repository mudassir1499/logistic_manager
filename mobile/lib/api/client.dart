import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Thrown for anything the caller should show the user.
///
/// The API answers errors as JSON with either a `detail` string or a map of
/// field -> [messages]. Both are flattened here so a screen can print
/// `e.message` without knowing which shape arrived.
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode, this.fieldErrors});

  final String message;
  final int? statusCode;
  final Map<String, List<String>>? fieldErrors;

  /// True when the token is missing, expired or revoked.
  ///
  /// The app treats this as "sign in again" rather than as an error to show,
  /// because a revoked token cannot be recovered from by retrying.
  bool get isAuthFailure => statusCode == 401;

  @override
  String toString() => message;
}

/// Talks to /api/v1/.
///
/// One instance for the whole app, holding the bearer token. Every screen goes
/// through this rather than calling http directly, so the token, the base URL,
/// the JSON decoding and the error shape are defined once.
class ApiClient {
  ApiClient({String? baseUrl, http.Client? httpClient})
      : _baseUrl = _normaliseBase(baseUrl ?? defaultBaseUrl),
        _http = httpClient ?? http.Client();

  /// Where the API lives.
  ///
  /// Overridable at build time so the same binary can point at a local server:
  ///   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
  ///
  /// 10.0.2.2 rather than 127.0.0.1 is how the Android emulator reaches the
  /// host machine — localhost inside the emulator is the emulator itself.
  static const String defaultBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://mudassirllc.com',
  );

  static const _tokenKey = 'api_token';

  final String _baseUrl;
  final http.Client _http;
  String? _token;

  String? get token => _token;
  bool get isSignedIn => _token != null && _token!.isNotEmpty;

  static String _normaliseBase(String value) {
    var url = value.trim();
    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    return url;
  }

  /// Restore a token saved by a previous run.
  Future<void> loadToken() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_tokenKey);
    _token = (stored != null && stored.isNotEmpty) ? stored : null;
  }

  Future<void> _setToken(String? value) async {
    _token = value;
    final prefs = await SharedPreferences.getInstance();
    if (value == null || value.isEmpty) {
      await prefs.remove(_tokenKey);
    } else {
      await prefs.setString(_tokenKey, value);
    }
  }

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final cleaned = <String, String>{};
    query?.forEach((key, value) {
      if (value == null) return;
      final text = value.toString();
      if (text.isEmpty) return;
      cleaned[key] = text;
    });
    return Uri.parse('$_baseUrl/api/v1$path')
        .replace(queryParameters: cleaned.isEmpty ? null : cleaned);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (isSignedIn) 'Authorization': 'Bearer $_token',
      };

  /// Turn any response into decoded JSON, or throw something printable.
  dynamic _decode(http.Response response) {
    final status = response.statusCode;

    // 204 has no body by definition; decoding it would throw.
    if (status == 204 || response.bodyBytes.isEmpty) {
      if (status >= 400) throw ApiException(_statusMessage(status), statusCode: status);
      return null;
    }

    dynamic body;
    try {
      // utf8.decode, not response.body: the latter guesses latin-1 when the
      // server omits a charset, which turns Chinese product names into mojibake.
      body = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      // An HTML error page from the web server rather than the app — a 502, or
      // a request too large. Not something to show raw.
      throw ApiException(_statusMessage(status), statusCode: status);
    }

    if (status >= 200 && status < 300) return body;

    throw _errorFrom(body, status);
  }

  ApiException _errorFrom(dynamic body, int status) {
    if (body is Map<String, dynamic>) {
      final detail = body['detail'];
      if (detail is String && detail.isNotEmpty) {
        return ApiException(detail, statusCode: status);
      }

      // DRF field errors: {"password": ["too short"], "email": ["taken"]}.
      final fields = <String, List<String>>{};
      body.forEach((key, value) {
        if (value is List) {
          fields[key] = value.map((v) => v.toString()).toList();
        } else if (value is String) {
          fields[key] = [value];
        }
      });
      if (fields.isNotEmpty) {
        final first = fields.values.first.first;
        return ApiException(first, statusCode: status, fieldErrors: fields);
      }
    }
    return ApiException(_statusMessage(status), statusCode: status);
  }

  String _statusMessage(int status) {
    switch (status) {
      case 401:
        return 'Your session has expired. Please sign in again.';
      case 403:
        return 'You do not have permission to do that.';
      case 404:
        return 'Not found.';
      case 429:
        return 'Too many attempts. Please wait a moment and try again.';
      case 500:
      case 502:
      case 503:
        return 'The server is having trouble. Please try again shortly.';
      default:
        return 'Something went wrong (HTTP $status).';
    }
  }

  Future<dynamic> _send(
    String method,
    String path, {
    Map<String, dynamic>? query,
    Object? body,
  }) async {
    final uri = _uri(path, query);
    try {
      late http.Response response;
      final encoded = body == null ? null : jsonEncode(body);
      switch (method) {
        case 'GET':
          response = await _http.get(uri, headers: _headers);
          break;
        case 'POST':
          response = await _http.post(uri, headers: _headers, body: encoded);
          break;
        case 'PATCH':
          response = await _http.patch(uri, headers: _headers, body: encoded);
          break;
        case 'DELETE':
          response = await _http.delete(uri, headers: _headers, body: encoded);
          break;
        default:
          throw ArgumentError('Unsupported method $method');
      }
      return _decode(response);
    } on ApiException {
      rethrow;
    } catch (error) {
      // Socket errors, DNS failures, TLS problems. The user cannot act on the
      // detail, and showing "SocketException: Failed host lookup" helps nobody.
      throw ApiException('Could not reach the server. Check your connection.');
    }
  }

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _send('GET', path, query: query);
  Future<dynamic> post(String path, {Object? body}) => _send('POST', path, body: body);
  Future<dynamic> patch(String path, {Object? body}) => _send('PATCH', path, body: body);
  Future<dynamic> delete(String path) => _send('DELETE', path);

  // ---- Auth ---------------------------------------------------------------

  Future<void> login({required String email, required String password}) async {
    final data = await post('/auth/login/', body: {'email': email, 'password': password});
    await _setToken(data['token'] as String);
  }

  Future<void> register({
    required String name,
    required String email,
    required String password,
    String phone = '',
    String address = '',
  }) async {
    final data = await post('/auth/register/', body: {
      'name': name,
      'email': email,
      'password': password,
      'phone': phone,
      'address': address,
    });
    await _setToken(data['token'] as String);
  }

  /// Revoke this token server-side, then forget it locally.
  ///
  /// The local token is cleared even when the call fails: if the server is
  /// unreachable the user still expects to be signed out, and a token left in
  /// storage would sign them straight back in on the next launch.
  Future<void> logout() async {
    try {
      await post('/auth/logout/');
    } on ApiException {
      // Already invalid, or offline. Either way, drop it.
    }
    await _setToken(null);
  }

  Future<void> requestPasswordReset(String email) =>
      post('/auth/password-reset/', body: {'email': email});

  Future<void> clearTokenLocally() => _setToken(null);
}
