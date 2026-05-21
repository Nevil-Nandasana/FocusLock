import 'dart:math';
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';

import 'providers.dart';
import 'ui_components.dart';
import 'api_service.dart';

class ActiveSessionScreen extends ConsumerStatefulWidget {
  final bool isCompleted;
  
  const ActiveSessionScreen({super.key, required this.isCompleted});

  @override
  ConsumerState<ActiveSessionScreen> createState() => _ActiveSessionScreenState();
}

class _ActiveSessionScreenState extends ConsumerState<ActiveSessionScreen> with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;

  Future<void> _togglePause(bool currentlyPaused) async {
    final success = await ApiService.setAfk(!currentlyPaused);
    if (!mounted) {
      return;
    }
    if (!success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not update pause state')),
      );
      return;
    }
    await ref.read(statusProvider.notifier).refreshNow();
  }

  Future<void> _breakSession() async {
    final excuseController = TextEditingController();
    final excuse = await showDialog<String>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          backgroundColor: const Color(0xFF1A1B2B),
          title: const Text('Break Session', style: TextStyle(color: Colors.white)),
          content: TextField(
            controller: excuseController,
            autofocus: true,
            style: const TextStyle(color: Colors.white),
            decoration: const InputDecoration(
              hintText: 'Enter your reason',
              hintStyle: TextStyle(color: Colors.white54),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, excuseController.text.trim()),
              child: const Text('Confirm'),
            ),
          ],
        );
      },
    );
    excuseController.dispose();

    if (!mounted || excuse == null || excuse.isEmpty) {
      return;
    }
    final success = await ApiService.breakSession(excuse);
    if (!mounted) {
      return;
    }
    if (!success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not break session')),
      );
      return;
    }
    await ref.read(statusProvider.notifier).refreshNow();
  }
  
  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  String _formatTime(int totalSeconds) {
    int minutes = totalSeconds ~/ 60;
    int seconds = totalSeconds % 60;
    return '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final status = ref.watch(statusProvider);
    final remaining = status['remaining'] ?? 0;
    final isPaused = status['paused'] == true;
    final currentState = '${status['current_state'] ?? ''}';
    final isDistracted = (status['recovery_active'] == true || currentState == 'DISTRACTION') && !widget.isCompleted;
    final recoverySnapshot = status['recovery_snapshot'];

    return Scaffold(
      body: Stack(
        children: [
          const AnimatedBackground(),
          SafeArea(
            child: Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    'FOCUS MODE ACTIVE',
                    style: GoogleFonts.outfit(
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 8,
                      color: const Color(0xFF6366F1),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'Current Category: ${status['mode'] == 'deep' ? "Deep Work" : "Standard"}',
                    style: GoogleFonts.inter(
                      fontSize: 16,
                      color: Colors.white70,
                    ),
                  ),
                  const SizedBox(height: 64),
                  AnimatedBuilder(
                    animation: _pulseController,
                    builder: (context, child) {
                      return Container(
                        width: 280,
                        height: 280,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: const Color(0xFF6366F1).withValues(alpha: 0.1 + (_pulseController.value * 0.1)),
                          boxShadow: [
                            BoxShadow(
                              color: const Color(0xFF6366F1).withValues(alpha: 0.2 * _pulseController.value),
                              blurRadius: 50,
                              spreadRadius: 20,
                            ),
                          ],
                          border: Border.all(
                            color: const Color(0xFF6366F1).withValues(alpha: 0.5 + (_pulseController.value * 0.5)),
                            width: 2,
                          ),
                        ),
                        alignment: Alignment.center,
                        child: Text(
                          _formatTime(remaining),
                          style: GoogleFonts.outfit(
                            fontSize: 72,
                            fontWeight: FontWeight.bold,
                            color: Colors.white,
                          ),
                        ),
                      );
                    },
                  ),
                  const SizedBox(height: 64),
                  if (status['streak'] != null && status['streak'] > 1) 
                    Text(
                      '🔥 Streak: ${status['streak']}x Multiplier',
                      style: GoogleFonts.inter(
                        fontSize: 18,
                        color: Colors.orangeAccent,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  const SizedBox(height: 24),
                  if (!widget.isCompleted)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 24),
                      child: Row(
                        children: [
                          Expanded(
                            child: PrimaryButton(
                              label: isPaused ? 'Resume' : 'Pause',
                              isSecondary: true,
                              onPressed: () => _togglePause(isPaused),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: PrimaryButton(
                              label: 'Break Session',
                              onPressed: _breakSession,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
          
          if (isDistracted)
            _buildDistractionLightbox(recoverySnapshot),
            
          if (widget.isCompleted)
            _buildCompletionLightbox(status),
        ],
      ),
    );
  }

  Widget _buildDistractionLightbox(dynamic recoverySnapshot) {
    final app = recoverySnapshot is Map<String, dynamic> ? recoverySnapshot['app'] : '';
    final title = recoverySnapshot is Map<String, dynamic> ? recoverySnapshot['title'] : '';
    final reason = recoverySnapshot is Map<String, dynamic> ? recoverySnapshot['reason'] : '';

    return BackdropFilter(
      filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
      child: Container(
        color: Colors.black.withValues(alpha: 0.4),
        alignment: Alignment.center,
        child: AnimatedScale(
          scale: 1.0,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOutBack,
          child: GlassCard(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 48),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.warning_amber_rounded, size: 80, color: Colors.orangeAccent),
                const SizedBox(height: 24),
                Text(
                  'Distraction Detected',
                  style: GoogleFonts.outfit(
                    fontSize: 32,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  'FocusLock AI detected an off-task activity.\nClose the distractive window immediately and get back to work.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.inter(
                    fontSize: 16,
                    color: Colors.white70,
                    height: 1.5,
                  ),
                ),
                if ('$app$title$reason'.trim().isNotEmpty) ...[
                  const SizedBox(height: 16),
                  Text(
                    'App: $app\nTitle: $title\nReason: $reason',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.inter(
                      fontSize: 14,
                      color: Colors.white60,
                      height: 1.4,
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                Row(
                  children: [
                    Expanded(
                      child: PrimaryButton(
                        label: 'I Corrected It',
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
                        label: 'Ignore',
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
    );
  }

  Widget _buildCompletionLightbox(Map<String, dynamic> status) {
    final summary = status['summary'] ?? {};
    final duration = summary['duration'] ?? 25;
    final violations = summary['violations'] ?? 0;
    final streak = summary['streak'] ?? 1;
    final focusScore = max(0, 100 - (violations * 10)) * streak;

    return BackdropFilter(
      filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
      child: Container(
        color: Colors.black.withValues(alpha: 0.6),
        alignment: Alignment.center,
        child: AnimatedScale(
          scale: 1.0,
          duration: const Duration(milliseconds: 500),
          curve: Curves.easeOutCirc,
          child: GlassCard(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 48),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Session Complete 🎉',
                  style: GoogleFonts.outfit(
                    fontSize: 36,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 32),
                Text(
                  'Time Summary: $duration Minutes\nViolations: $violations\nStreak: ${streak}x',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.inter(
                    fontSize: 18,
                    color: Colors.white70,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  'Focus Score: $focusScore',
                  style: GoogleFonts.outfit(
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                    color: const Color(0xFF6366F1),
                  ),
                ),
                const SizedBox(height: 48),
                PrimaryButton(
                  label: 'Continue (+10 min & +Streak)',
                  onPressed: () async {
                    await ApiService.continueSession(10);
                  },
                ),
                const SizedBox(height: 16),
                PrimaryButton(
                  label: 'Stop Session',
                  isSecondary: true,
                  onPressed: () async {
                    await ApiService.stopSession();
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
