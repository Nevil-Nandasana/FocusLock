import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api_service.dart';

// ── Default host ────────────────────────────────────────────────────────────
const String _kDefaultHost = 'http://127.0.0.1:5000/api';
const String _kPrefKey = 'focuslock_host_url';

// ── Connection state ─────────────────────────────────────────────────────────

class HostConnectionState {
  final String hostUrl;
  final bool isConnected;
  final String? lastError;

  const HostConnectionState({
    required this.hostUrl,
    required this.isConnected,
    this.lastError,
  });

  HostConnectionState copyWith({
    String? hostUrl,
    bool? isConnected,
    String? lastError,
  }) {
    return HostConnectionState(
      hostUrl: hostUrl ?? this.hostUrl,
      isConnected: isConnected ?? this.isConnected,
      lastError: lastError,
    );
  }
}

class ConnectionNotifier extends AsyncNotifier<HostConnectionState> {
  @override
  Future<HostConnectionState> build() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_kPrefKey);
    final host = (saved != null && saved.isNotEmpty) ? saved : _kDefaultHost;
    // Perform an initial probe so the UI starts with correct connected state.
    return await _probe(host);
  }

  Future<HostConnectionState> _probe(String host) async {
    try {
      final ok = await ApiService.probeHost(host);
      return HostConnectionState(hostUrl: host, isConnected: ok, lastError: ok ? null : 'Host unreachable');
    } catch (e) {
      return HostConnectionState(hostUrl: host, isConnected: false, lastError: e.toString());
    }
  }

  /// Save a new host URL, persist it, and immediately probe it.
  Future<void> setHost(String host) async {
    state = const AsyncLoading();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kPrefKey, host);
    ApiService.setHostUrl(host);
    final result = await _probe(host);
    state = AsyncData(result);
  }

  /// Re-probe the current host (called by status poller on each tick).
  Future<void> recheck() async {
    final current = state.valueOrNull;
    if (current == null) return;
    final result = await _probe(current.hostUrl);
    state = AsyncData(result);
  }
}

final connectionProvider =
    AsyncNotifierProvider<ConnectionNotifier, HostConnectionState>(ConnectionNotifier.new);

// ── Status polling ───────────────────────────────────────────────────────────

class StatusNotifier extends Notifier<Map<String, dynamic>> {
  Timer? _timer;
  bool _isPolling = false;

  @override
  Map<String, dynamic> build() {
    _startPolling();
    unawaited(refreshNow());
    ref.onDispose(() {
      _timer?.cancel();
    });
    return {'active': false};
  }

  void _startPolling() {
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) async {
      await refreshNow();
    });
  }

  Future<void> refreshNow() async {
    if (_isPolling) {
      return;
    }
    _isPolling = true;
    try {
      final status = await ApiService.getStatus();
      if (status.containsKey('error')) {
        // Mark connection as broken when status calls fail.
        final connNotifier = ref.read(connectionProvider.notifier);
        await connNotifier.recheck();
      } else {
        state = status;
        // Keep connection marked healthy.
        final conn = ref.read(connectionProvider).valueOrNull;
        if (conn != null && !conn.isConnected) {
          await ref.read(connectionProvider.notifier).recheck();
        }
      }
    } finally {
      _isPolling = false;
    }
  }
}

final statusProvider =
    NotifierProvider<StatusNotifier, Map<String, dynamic>>(StatusNotifier.new);
