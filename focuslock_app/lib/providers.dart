import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'api_service.dart';

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
      if (!status.containsKey('error')) {
        state = status;
      }
    } finally {
      _isPolling = false;
    }
  }
}

final statusProvider = NotifierProvider<StatusNotifier, Map<String, dynamic>>(StatusNotifier.new);
