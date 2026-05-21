import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

class ApiService {
  static const String _baseUrlFromEnv = String.fromEnvironment('API_BASE_URL', defaultValue: '');
  static const String _apiKey = String.fromEnvironment('FOCUSLOCK_API_KEY', defaultValue: '');

  static String get baseUrl {
    if (_baseUrlFromEnv.isNotEmpty) {
      return _baseUrlFromEnv;
    }
    if (kIsWeb) {
      return 'http://127.0.0.1:5000/api';
    }
    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:5000/api';
    }
    return 'http://127.0.0.1:5000/api';
  }

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

  static Future<Map<String, dynamic>> _get(String path) async {
    final response = await http
        .get(Uri.parse('$baseUrl/$path'), headers: _headers())
        .timeout(const Duration(seconds: 3));
    return _decodeMap(response.body, response.statusCode);
  }

  static Future<Map<String, dynamic>> _post(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final response = await http
        .post(
          Uri.parse('$baseUrl/$path'),
          headers: _headers(includeJson: body != null),
          body: body == null ? null : jsonEncode(body),
        )
        .timeout(const Duration(seconds: 3));
    return _decodeMap(response.body, response.statusCode);
  }

  static Map<String, dynamic> _decodeMap(String body, int statusCode) {
    final decoded = jsonDecode(body);
    if (decoded is Map<String, dynamic>) {
      return {
        ...decoded,
        '_statusCode': statusCode,
      };
    }
    return {'error': 'Unexpected response format', '_statusCode': statusCode};
  }

  static bool _isSuccess(Map<String, dynamic> response) {
    final statusCode = response['_statusCode'];
    return statusCode is int && statusCode >= 200 && statusCode < 300;
  }

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
}
