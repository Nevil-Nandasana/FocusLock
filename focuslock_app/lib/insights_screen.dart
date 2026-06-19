import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';

import 'api_service.dart';
import 'profile_screen.dart';
import 'providers.dart';
import 'ui_components.dart';

class InsightsScreen extends ConsumerStatefulWidget {
  const InsightsScreen({super.key});

  @override
  ConsumerState<InsightsScreen> createState() => _InsightsScreenState();
}

class _InsightsScreenState extends ConsumerState<InsightsScreen> {
  Map<String, dynamic>? _profile;
  Map<String, dynamic>? _integrity;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadInsights();
  }

  Future<void> _loadInsights() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    final profile = await ApiService.getProfile();
    final integrity = await ApiService.getIntegrity();
    await ref.read(statusProvider.notifier).refreshNow();

    if (!mounted) {
      return;
    }

    if (profile.containsKey('error') || integrity.containsKey('error')) {
      setState(() {
        _error = 'Could not fetch insights from FocusLock backend.';
        _loading = false;
      });
      return;
    }

    setState(() {
      _profile = profile;
      _integrity = integrity;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final status = ref.watch(statusProvider);
    final stats = (status['user_stats'] is Map<String, dynamic>)
        ? status['user_stats'] as Map<String, dynamic>
        : <String, dynamic>{};

    final totalSessions = _asInt(stats['total_sessions']);
    final completedSessions = _asInt(stats['completed_sessions']);
    final successRate = totalSessions == 0 ? 0 : ((completedSessions * 100) / totalSessions).round();

    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        title: Text('Insights', style: GoogleFonts.outfit(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: Stack(
        children: [
          const AnimatedBackground(),
          SafeArea(
            child: RefreshIndicator(
              onRefresh: _loadInsights,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                children: [
                  if (_loading)
                    const Padding(
                      padding: EdgeInsets.only(top: 80),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                  if (_error != null)
                    GlassCard(
                      child: Text(
                        _error!,
                        style: GoogleFonts.inter(color: Colors.white),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  if (!_loading && _error == null) ...[
                    Row(
                      children: [
                        Expanded(
                          child: _MetricCard(
                            title: 'Level',
                            value: '${_asInt(stats['level'])}',
                            subtitle: 'Current rank',
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: _MetricCard(
                            title: 'XP',
                            value: '${_asInt(stats['xp'])}',
                            subtitle: 'Accumulated points',
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: _MetricCard(
                            title: 'Consistency',
                            value: '$successRate%',
                            subtitle: '$completedSessions of $totalSessions sessions',
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: _MetricCard(
                            title: 'Integrity',
                            value: (_integrity?['valid'] == true) ? 'Valid' : 'Check',
                            subtitle: '${_integrity?['message'] ?? 'Unknown'}',
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    _DetailsCard(
                      title: 'ML Status',
                      content: _formatMap(_profile?['ml_status']),
                    ),
                    const SizedBox(height: 12),
                    _DetailsCard(
                      title: 'Intent Profile',
                      content: _formatMap(_profile?['intent_profile']),
                    ),
                    const SizedBox(height: 12),
                    _DetailsCard(
                      title: 'User Profile',
                      content: _formatMap(_profile?['profile']),
                    ),
                    const SizedBox(height: 12),
                    _DetailsCard(
                      title: 'Live Session Snapshot',
                      content: _formatMap({
                        'active': status['active'],
                        'mode': status['mode'],
                        'remaining': status['remaining'],
                        'state': status['current_state'],
                        'prediction': status['prediction'],
                        'paused': status['paused'],
                      }),
                    ),
                    const SizedBox(height: 16),
                    PrimaryButton(
                      label: 'AI Profile & Weights →',
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => const ProfileScreen()),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  int _asInt(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return 0;
  }

  String _formatMap(dynamic data) {
    if (data is! Map) {
      return 'No data available';
    }
    if (data.isEmpty) {
      return 'No data available';
    }
    return data.entries.map((entry) => '${entry.key}: ${entry.value}').join('\n');
  }
}

class _MetricCard extends StatelessWidget {
  final String title;
  final String value;
  final String subtitle;

  const _MetricCard({
    required this.title,
    required this.value,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: GoogleFonts.inter(color: Colors.white70, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: GoogleFonts.outfit(
              fontSize: 30,
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            subtitle,
            style: GoogleFonts.inter(color: Colors.white60, fontSize: 13),
          ),
        ],
      ),
    );
  }
}

class _DetailsCard extends StatelessWidget {
  final String title;
  final String content;

  const _DetailsCard({
    required this.title,
    required this.content,
  });

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: GoogleFonts.outfit(
              color: Colors.white,
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            content,
            style: GoogleFonts.inter(
              color: Colors.white70,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}
