import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';

import 'api_service.dart';
import 'providers.dart';
import 'ui_components.dart';

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  final TextEditingController _intentController = TextEditingController();
  final TextEditingController _whitelistController = TextEditingController();
  final TextEditingController _durationController = TextEditingController(text: '25');
  final TextEditingController _breakController = TextEditingController();

  String _selectedMode = 'deep';
  Map<String, dynamic>? _profile;
  Map<String, dynamic>? _integrity;
  bool _loadingMeta = true;
  bool _showModeOptions = false;

  @override
  void initState() {
    super.initState();
    _loadMeta();
  }

  @override
  void dispose() {
    _intentController.dispose();
    _whitelistController.dispose();
    _durationController.dispose();
    _breakController.dispose();
    super.dispose();
  }

  Future<void> _loadMeta() async {
    setState(() {
      _loadingMeta = true;
    });

    final profile = await ApiService.getProfile();
    final integrity = await ApiService.getIntegrity();
    await ref.read(statusProvider.notifier).refreshNow();

    if (!mounted) {
      return;
    }

    setState(() {
      _profile = profile.containsKey('error') ? null : profile;
      _integrity = integrity.containsKey('error') ? null : integrity;
      _loadingMeta = false;
    });
  }

  Future<void> _startSession() async {
    final duration = int.tryParse(_durationController.text.trim()) ?? 25;
    final whitelist = _whitelistController.text
        .split(',')
        .map((value) => value.trim())
        .where((value) => value.isNotEmpty)
        .toList();

    final success = await ApiService.startSession(
      duration: duration,
      mode: _selectedMode,
      intent: _intentController.text.trim(),
      whitelist: whitelist,
      blacklist: const [],
    );

    if (!mounted) {
      return;
    }

    if (!success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Failed to start session')),
      );
      return;
    }

    await ref.read(statusProvider.notifier).refreshNow();
  }

  Future<void> _continueSession() async {
    final success = await ApiService.continueSession(10);
    if (!mounted) {
      return;
    }
    if (!success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Failed to extend session')),
      );
      return;
    }
    await ref.read(statusProvider.notifier).refreshNow();
  }

  Future<void> _stopSession() async {
    await ApiService.stopSession();
    if (!mounted) {
      return;
    }
    await ref.read(statusProvider.notifier).refreshNow();
  }

  Future<void> _breakSession() async {
    final excuse = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return AlertDialog(
          backgroundColor: const Color(0xFF14121E),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
          title: Text(
            'Emergency Break',
            style: GoogleFonts.outfit(color: Colors.white, fontWeight: FontWeight.bold),
          ),
          content: TextField(
            controller: _breakController,
            autofocus: true,
            style: const TextStyle(color: Colors.white),
            decoration: InputDecoration(
              hintText: 'Enter your reason...',
              hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.45)),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, _breakController.text.trim()),
              child: const Text('Confirm'),
            ),
          ],
        );
      },
    );

    if (!mounted) {
      return;
    }

    if (excuse == null || excuse.isEmpty) {
      return;
    }

    await ApiService.breakSession(excuse);
    _breakController.clear();
    await ref.read(statusProvider.notifier).refreshNow();
  }

  @override
  Widget build(BuildContext context) {
    final status = ref.watch(statusProvider);
    final isActive = status['active'] == true;
    final isCompleted = status['completed'] == true;
    final userStats = (status['user_stats'] is Map<String, dynamic>)
        ? status['user_stats'] as Map<String, dynamic>
        : <String, dynamic>{};
    final currentState = '${status['current_state'] ?? 'PRODUCTIVE'}';
    final activity = (status['activity_snapshot'] is Map<String, dynamic>)
        ? status['activity_snapshot'] as Map<String, dynamic>
        : <String, dynamic>{};
    final prediction = status['prediction'];
    final recoveryActive = status['recovery_active'] == true;
    final recoverySnapshot = (status['recovery_snapshot'] is Map<String, dynamic>)
        ? status['recovery_snapshot'] as Map<String, dynamic>
        : <String, dynamic>{};

    final summary = (status['summary'] is Map<String, dynamic>)
        ? status['summary'] as Map<String, dynamic>
        : <String, dynamic>{};

    return Scaffold(
      body: Stack(
        children: [
          const AnimatedBackground(),
          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 520),
                  child: GlassCard(
                    padding: const EdgeInsets.all(28),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _buildHeader(userStats),
                        const SizedBox(height: 28),
                        if (!isActive && !isCompleted) ...[
                          _buildSetupForm(),
                        ] else if (isActive) ...[
                          _buildActiveView(status, activity, currentState, prediction),
                        ] else ...[
                          _buildCompletionView(summary, userStats),
                        ],
                        const SizedBox(height: 20),
                        if (_loadingMeta)
                          const Center(child: Padding(
                            padding: EdgeInsets.only(top: 8),
                            child: CircularProgressIndicator(),
                          )),
                        if (!_loadingMeta) ...[
                          const SizedBox(height: 8),
                          _buildMetaRow(),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
          if (recoveryActive)
            _buildRecoveryOverlay(recoverySnapshot),
          if (isActive && prediction is Map<String, dynamic> && prediction['warning'] == true)
            _buildPredictionToast(prediction),
        ],
      ),
    );
  }

  Widget _buildHeader(Map<String, dynamic> userStats) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Container(
          width: 96,
          height: 96,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: const LinearGradient(colors: [Color(0xFF6643ED), Color(0xFF3B82F6)]),
            boxShadow: [
              BoxShadow(
                color: const Color(0xFF6643ED).withValues(alpha: 0.35),
                blurRadius: 32,
                offset: const Offset(0, 10),
              ),
            ],
          ),
          child: const Icon(Icons.lock_outline, color: Colors.white, size: 44),
        ),
        const SizedBox(height: 26),
        Text(
          'FocusLock',
          textAlign: TextAlign.center,
          style: GoogleFonts.outfit(
            fontSize: 42,
            fontWeight: FontWeight.w800,
            color: Colors.white,
            letterSpacing: -0.8,
          ),
        ),
        const SizedBox(height: 10),
        Text(
          'Cognitive Behavior Engine',
          textAlign: TextAlign.center,
          style: GoogleFonts.inter(
            fontSize: 15,
            color: Colors.white70,
          ),
        ),
        const SizedBox(height: 16),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _pill('LVL ${_toInt(userStats['level'], fallback: 1)}', active: true),
            const SizedBox(width: 8),
            _pill('XP ${_toInt(userStats['xp'])}'),
          ],
        ),
      ],
    );
  }

  Widget _buildSetupForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _sectionTitle('Goal / Intent'),
        const SizedBox(height: 10),
        _glassField(
          child: TextField(
            controller: _intentController,
            maxLines: 2,
            style: const TextStyle(color: Colors.white),
            decoration: InputDecoration(
              border: InputBorder.none,
              hintText: 'e.g. Build authentication with React + Firebase',
              hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.45)),
            ),
          ),
        ),
        const SizedBox(height: 18),
        _sectionTitle('Duration (minutes)'),
        const SizedBox(height: 10),
        _glassField(
          child: TextField(
            controller: _durationController,
            keyboardType: TextInputType.number,
            style: const TextStyle(color: Colors.white),
            decoration: InputDecoration(
              border: InputBorder.none,
              hintText: '25',
              hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.45)),
            ),
          ),
        ),
        const SizedBox(height: 18),
        _sectionTitle('Mode'),
        const SizedBox(height: 10),
        GestureDetector(
          onTap: () => setState(() => _showModeOptions = !_showModeOptions),
          child: _glassField(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    _selectedMode == 'deep' ? 'Deep Work (Strict)' : 'Standard (Lenient)',
                    style: GoogleFonts.inter(color: Colors.white),
                  ),
                ),
                const Icon(Icons.keyboard_arrow_down, color: Colors.white70),
              ],
            ),
          ),
        ),
        if (_showModeOptions) ...[
          const SizedBox(height: 8),
          _modeOption('deep', 'Deep Work (Strict)'),
          const SizedBox(height: 8),
          _modeOption('standard', 'Standard (Lenient)'),
        ],
        const SizedBox(height: 18),
        _sectionTitle('Whitelist (optional)'),
        const SizedBox(height: 10),
        _glassField(
          child: TextField(
            controller: _whitelistController,
            style: const TextStyle(color: Colors.white),
            decoration: InputDecoration(
              border: InputBorder.none,
              hintText: 'e.g. stackoverflow, docs, localhost',
              hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.45)),
            ),
          ),
        ),
        const SizedBox(height: 22),
        PrimaryButton(
          label: 'INITIALIZE ENGINE',
          onPressed: _startSession,
        ),
      ],
    );
  }

  Widget _buildActiveView(
    Map<String, dynamic> status,
    Map<String, dynamic> activity,
    String currentState,
    dynamic prediction,
  ) {
    final features = (activity['features'] is Map<String, dynamic>)
        ? activity['features'] as Map<String, dynamic>
        : <String, dynamic>{};
    final remaining = _toInt(status['remaining']);
    final penalties = _toInt(status['penalties']);
    final intentProfile = (status['intent_profile'] is Map<String, dynamic>)
        ? status['intent_profile'] as Map<String, dynamic>
        : <String, dynamic>{};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _innerPanel(
          child: Column(
            children: [
              Text(
                _formatTime(remaining),
                style: GoogleFonts.outfit(
                  fontSize: 72,
                  fontWeight: FontWeight.w800,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'REMAINING',
                style: GoogleFonts.inter(color: Colors.white70, letterSpacing: 2),
              ),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _pill(currentState, active: currentState == 'PRODUCTIVE'),
                  const SizedBox(width: 8),
                  _pill('DEBT ${penalties}s', active: false),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (intentProfile.isNotEmpty)
          _innerPanel(
            child: Text(
              'Current Intent: ${intentProfile['goal_verb'] ?? ''} ${intentProfile['goal_subject'] ?? ''}'.trim(),
              textAlign: TextAlign.center,
              style: GoogleFonts.inter(
                color: Colors.white70,
                fontStyle: FontStyle.italic,
              ),
            ),
          ),
        if (intentProfile.isNotEmpty) const SizedBox(height: 16),
        _sectionTitle('Live Telemetry'),
        const SizedBox(height: 10),
        _innerPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text(
                      '${activity['app'] ?? '—'}',
                      style: GoogleFonts.inter(
                        color: const Color(0xFF8E8CFF),
                        fontWeight: FontWeight.w700,
                        fontSize: 13,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  Text(
                    '${_toInt(features['latency_ms'])}ms',
                    style: GoogleFonts.jetBrainsMono(
                      color: Colors.white54,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                '${activity['title'] ?? 'Waiting for telemetry...'}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: GoogleFonts.jetBrainsMono(
                  color: Colors.white54,
                  fontSize: 11,
                ),
              ),
              const SizedBox(height: 18),
              _metricBar('CONFIDENCE', _toDouble(features['confidence']) / 100, '${_toDouble(features['confidence']).round()}%'),
              const SizedBox(height: 14),
              _metricBar('SEMANTIC MATCH', _toDouble(features['semantic_similarity']), _toDouble(features['semantic_similarity']).toStringAsFixed(2), accent: const Color(0xFFF59E0B)),
            ],
          ),
        ),
        if (prediction is Map<String, dynamic> && prediction['warning'] == true) ...[
          const SizedBox(height: 16),
          _innerPanel(
            borderColor: const Color(0xFFEF4444).withValues(alpha: 0.35),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'FAILURE PREDICTED',
                  style: GoogleFonts.outfit(
                    color: const Color(0xFFFCA5A5),
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.5,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  (prediction['reasons'] as List?)?.join(', ') ?? 'No reason provided',
                  style: GoogleFonts.jetBrainsMono(color: Colors.white60, fontSize: 11, height: 1.4),
                ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: PrimaryButton(
                label: 'EMERGENCY BREAK',
                onPressed: _breakSession,
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: PrimaryButton(
                label: 'Continue +10 MIN',
                isSecondary: true,
                onPressed: _continueSession,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: PrimaryButton(
                label: 'End Session',
                isSecondary: true,
                onPressed: _stopSession,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildCompletionView(Map<String, dynamic> summary, Map<String, dynamic> userStats) {
    final duration = _toInt(summary['duration'], fallback: 25);
    final violations = _toInt(summary['violations']);
    final streak = _toInt(summary['streak'], fallback: 1);
    final totalDistractions = _toInt(summary['total_distractions']);
    final corrected = _toInt(summary['corrected_distractions']);
    final consistency = totalDistractions > 0 ? ((corrected / totalDistractions) * 100).round() : 100;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _innerPanel(
          child: Column(
            children: [
              Text(
                'Session Complete',
                textAlign: TextAlign.center,
                style: GoogleFonts.outfit(
                  fontSize: 32,
                  fontWeight: FontWeight.w800,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 18),
              Text(
                'Time Summary: $duration Minutes\nViolations: $violations\nStreak: ${streak}x',
                textAlign: TextAlign.center,
                style: GoogleFonts.inter(
                  color: Colors.white70,
                  height: 1.6,
                ),
              ),
              const SizedBox(height: 14),
              Text(
                'Focus Score: ${_focusScore(violations, streak)}',
                style: GoogleFonts.outfit(
                  fontSize: 42,
                  color: const Color(0xFF8E8CFF),
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 18),
              Text(
                'Recovery: $consistency%\nXP Earned: ${_toInt(userStats['xp'])}',
                textAlign: TextAlign.center,
                style: GoogleFonts.jetBrainsMono(
                  color: Colors.white60,
                  fontSize: 12,
                  height: 1.5,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: PrimaryButton(
                label: '+10 MIN & STREAK',
                onPressed: _continueSession,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: PrimaryButton(
                label: 'END SESSION',
                isSecondary: true,
                onPressed: _stopSession,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildRecoveryOverlay(Map<String, dynamic> recoverySnapshot) {
    return Positioned.fill(
      child: Container(
        color: Colors.black.withValues(alpha: 0.55),
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: GlassCard(
                padding: const EdgeInsets.all(26),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.cancel_outlined, color: Color(0xFFEF4444), size: 56),
                    const SizedBox(height: 18),
                    Text(
                      'You’ve drifted from your goal',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.outfit(
                        fontSize: 28,
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'This activity doesn’t align with your current focus session.',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.inter(color: Colors.white70, height: 1.5),
                    ),
                    const SizedBox(height: 14),
                    _innerPanel(
                      padding: const EdgeInsets.all(14),
                      borderColor: Colors.white.withValues(alpha: 0.08),
                      child: Text(
                        '${recoverySnapshot['reason'] ?? 'Analyzing...'}',
                        textAlign: TextAlign.center,
                        style: GoogleFonts.jetBrainsMono(color: Colors.white70, fontSize: 11),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: PrimaryButton(
                            label: 'RETURN TO FOCUS',
                            onPressed: () async {
                              await ApiService.markRecoveryCorrect();
                              if (!mounted) {
                                return;
                              }
                              await ref.read(statusProvider.notifier).refreshNow();
                            },
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: PrimaryButton(
                            label: 'IGNORE',
                            isSecondary: true,
                            onPressed: () async {
                              await ApiService.markRecoveryIgnore();
                              if (!mounted) {
                                return;
                              }
                              await ref.read(statusProvider.notifier).refreshNow();
                            },
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildPredictionToast(Map<String, dynamic> prediction) {
    return Positioned(
      top: 20,
      left: 16,
      right: 16,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: GlassCard(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
            child: Column(
              children: [
                Text(
                  '⚠ FAILURE PREDICTED',
                  style: GoogleFonts.outfit(
                    color: const Color(0xFFFCA5A5),
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.5,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  (prediction['reasons'] as List?)?.join(', ') ?? 'No reason provided',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.jetBrainsMono(color: Colors.white60, fontSize: 10),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildMetaRow() {
    final valid = _integrity?['valid'] == true;
    return Row(
      children: [
        Expanded(
          child: _smallStatCard(
            title: 'Integrity',
            value: valid ? 'Valid' : 'Check',
            subtitle: '${_integrity?['message'] ?? 'Unknown'}',
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _smallStatCard(
            title: 'ML Status',
            value: _profile?['ml_status']?['ml_ready'] == true ? 'Ready' : 'Booting',
            subtitle: _profile?['ml_status']?['ml_error'] ?? 'Live backend connected',
          ),
        ),
      ],
    );
  }

  Widget _smallStatCard({
    required String title,
    required String value,
    required String subtitle,
  }) {
    return _innerPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: GoogleFonts.inter(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text(value, style: GoogleFonts.outfit(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text(subtitle, style: GoogleFonts.jetBrainsMono(color: Colors.white54, fontSize: 10, height: 1.4)),
        ],
      ),
    );
  }

  Widget _sectionTitle(String text) {
    return Text(
      text,
      style: GoogleFonts.inter(
        fontSize: 16,
        fontWeight: FontWeight.w700,
        color: Colors.white,
      ),
    );
  }

  Widget _glassField({required Widget child, EdgeInsetsGeometry padding = const EdgeInsets.all(10)}) {
    return _innerPanel(padding: padding, child: child);
  }

  Widget _innerPanel({
    required Widget child,
    EdgeInsetsGeometry padding = const EdgeInsets.all(18),
    Color? borderColor,
  }) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: borderColor ?? Colors.white.withValues(alpha: 0.14)),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Colors.white.withValues(alpha: 0.08),
            Colors.white.withValues(alpha: 0.03),
          ],
        ),
      ),
      child: Padding(
        padding: padding,
        child: child,
      ),
    );
  }

  Widget _metricBar(String label, double value, String text, {Color accent = const Color(0xFF6643ED)}) {
    final clamped = value.clamp(0.0, 1.0);
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: GoogleFonts.jetBrainsMono(color: Colors.white54, fontSize: 11)),
            Text(text, style: GoogleFonts.jetBrainsMono(color: Colors.white, fontSize: 11)),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: LinearProgressIndicator(
            value: clamped,
            minHeight: 8,
            backgroundColor: Colors.white.withValues(alpha: 0.08),
            valueColor: AlwaysStoppedAnimation<Color>(accent),
          ),
        ),
      ],
    );
  }

  Widget _pill(String label, {bool active = false}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
      decoration: BoxDecoration(
        color: active ? const Color(0xFF6643ED).withValues(alpha: 0.22) : Colors.white.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(99),
        border: Border.all(
          color: active ? const Color(0xFF6643ED).withValues(alpha: 0.35) : Colors.white.withValues(alpha: 0.08),
        ),
      ),
      child: Text(
        label,
        style: GoogleFonts.jetBrainsMono(
          color: Colors.white,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }

  Widget _modeOption(String value, String label) {
    final selected = _selectedMode == value;
    return GestureDetector(
      onTap: () {
        setState(() {
          _selectedMode = value;
          _showModeOptions = false;
        });
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          color: selected ? const Color(0xFF6643ED).withValues(alpha: 0.18) : Colors.white.withValues(alpha: 0.04),
          border: Border.all(color: selected ? const Color(0xFF6643ED).withValues(alpha: 0.35) : Colors.white.withValues(alpha: 0.08)),
        ),
        child: Text(
          label,
          style: GoogleFonts.inter(color: Colors.white, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }

  int _toInt(dynamic value, {int fallback = 0}) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return fallback;
  }

  double _toDouble(dynamic value) {
    if (value is double) {
      return value;
    }
    if (value is int) {
      return value.toDouble();
    }
    if (value is num) {
      return value.toDouble();
    }
    return 0.0;
  }

  String _formatTime(int totalSeconds) {
    final minutes = totalSeconds ~/ 60;
    final seconds = totalSeconds % 60;
    return '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';
  }

  int _focusScore(int violations, int streak) {
    return (100 - (violations * 10)).clamp(0, 100) * streak;
  }
}