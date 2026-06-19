import 'dart:convert';
import 'package:http/http.dart' as http;

/// Central HTTP client for the FocusLock backend.
///
/// **Platform model (Path A — Windows-tethered remote control)**
/// The monitoring engine only runs on the Windows host. This client connects
/// to whatever URL the user configures (defaults to localhost for Windows
/// builds; must be manually set to the host IP for Android/other platforms).
class ApiService {
  // ── Host configuration ─────────────────────────────────────────────────────
  // Runtime-mutable so [ConnectionNotifier.setHost] can update it without a
  // restart. Initialised to localhost; callers on non-Windows platforms must
  // call [setHostUrl] with the real Windows machine IP.

  static String _baseUrl = 'http://127.0.0.1:5000/api';
  static String get baseUrl => _baseUrl;

  static void setHostUrl(String url) {
    _baseUrl = url.endsWith('/api') ? url : '$url/api';
  }

  // ── Optional API key ────────────────────────────────────────────────────────
  static const String _apiKey =
      String.fromEnvironment('FOCUSLOCK_API_KEY', defaultValue: '');

  static Map<String, String> _headers({bool includeJson = false}) {
    final headers = <String, String>{};
    if (includeJson) {
      headers['Content-Type'] = 'application/json';
    }
    if (_apiKey.isNotEmpty) {
      headers['X-API-KEY'] = _apiKey;
    }
    return headers;
  }

  // ── Low-level helpers ───────────────────────────────────────────────────────

  static Future<Map<String, dynamic>> _get(String path) async {
    final response = await http
        .get(Uri.parse('$_baseUrl/$path'), headers: _headers())
        .timeout(const Duration(seconds: 3));
    return _decodeMap(response.body, response.statusCode);
  }

  static Future<Map<String, dynamic>> _post(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final response = await http
        .post(
          Uri.parse('$_baseUrl/$path'),
          headers: _headers(includeJson: body != null),
          body: body == null ? null : jsonEncode(body),
        )
        .timeout(const Duration(seconds: 3));
    return _decodeMap(response.body, response.statusCode);
  }

  static Map<String, dynamic> _decodeMap(String body, int statusCode) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        return {...decoded, '_statusCode': statusCode};
      }
    } catch (_) {}
    return {'error': 'Unexpected response format', '_statusCode': statusCode};
  }

  static bool _isSuccess(Map<String, dynamic> response) {
    final statusCode = response['_statusCode'];
    return statusCode is int && statusCode >= 200 && statusCode < 300;
  }

  // ── Connection probe ────────────────────────────────────────────────────────

  /// Returns true if [hostBaseUrl] responds to a `/health` check within 3 s.
  /// [hostBaseUrl] should be the API base URL (with or without `/api` suffix).
  static Future<bool> probeHost(String hostBaseUrl) async {
    try {
      // Derive the /health endpoint from whatever the caller provides.
      final base = hostBaseUrl.replaceAll(RegExp(r'/api/?$'), '');
      final response = await http
          .get(Uri.parse('$base/health'))
          .timeout(const Duration(seconds: 3));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  static Future<Map<String, dynamic>> getStatus() async {
    try {
      return await _get('status');
    } catch (e) {
      return {'error': e.toString()};
    }
  }

  static Future<bool> startSession({
    required int duration,
    required String mode,
    required String intent,
    required List<String> whitelist,
    required List<String> blacklist,
  }) async {
    try {
      final response = await _post(
        'start',
        body: {
          'duration': duration,
          'mode': mode,
          'intent': intent,
          'whitelist': whitelist,
          'blacklist': blacklist,
        },
      );
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }

  static Future<bool> stopSession() async {
    try {
      final response = await _post('stop');
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }

  static Future<bool> continueSession(int additionalMinutes) async {
    try {
      final response = await _post(
        'continue',
        body: {'duration': additionalMinutes},
      );
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }

  static Future<bool> setAfk(bool isAfk) async {
    try {
      final response = await _post('afk', body: {'status': isAfk});
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }

  static Future<bool> breakSession(String excuse) async {
    try {
      final response = await _post('break', body: {'excuse': excuse});
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }

  static Future<bool> markRecoveryCorrect() async {
    try {
      final response = await _post('recovery/correct');
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }

  static Future<bool> markRecoveryIgnore() async {
    try {
      final response = await _post('recovery/ignore');
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }

  static Future<Map<String, dynamic>> getProfile() async {
    try {
      return await _get('profile');
    } catch (e) {
      return {'error': e.toString()};
    }
  }

  static Future<Map<String, dynamic>> getIntegrity() async {
    try {
      return await _get('integrity');
    } catch (e) {
      return {'error': e.toString()};
    }
  }

  /// Fetch effective heuristic weights for [intentKey] from [/api/profile/weights].
  /// Returns {intent, buckets, weights, user_deltas}.
  static Future<Map<String, dynamic>> getProfileWeights(
      String intentKey) async {
    try {
      return await _get(
          'profile/weights?intent=${Uri.encodeComponent(intentKey)}');
    } catch (e) {
      return {'error': e.toString()};
    }
  }

  /// Post a manual feedback signal to [/api/feedback].
  /// [label] must be 'PRODUCTIVE' or 'DISTRACTION'.
  /// [concept] is typically the app name or a keyword concept.
  static Future<bool> submitFeedback({
    required String concept,
    required String label,
  }) async {
    try {
      final response = await _post(
        'feedback',
        body: {'app': concept, 'title': '', 'label': label},
      );
      return _isSuccess(response);
    } catch (e) {
      return false;
    }
  }
}
