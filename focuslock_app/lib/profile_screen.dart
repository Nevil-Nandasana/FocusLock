import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';

import 'api_service.dart';
import 'ui_components.dart';

/// Profile & Weights screen.
///
/// Surfaces the learned heuristic weights for each intent bucket and lets
/// the user correct them via thumbs-up / thumbs-down buttons.  Changes
/// are posted to [/api/feedback] which routes to [UserProfile.apply_feedback].
class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  // ── State ───────────────────────────────────────────────────────────────────
  bool _loading = true;
  String? _error;

  String _selectedBucket = 'global';
  List<String> _buckets = ['global'];

  /// concept → effective weight
  Map<String, int> _weights = {};

  /// concept → user-learned delta
  Map<String, int> _deltas = {};

  /// concept → true while a feedback call is in-flight
  final Map<String, bool> _pending = {};

  // ── Lifecycle ───────────────────────────────────────────────────────────────

  @override
  void initState() {
    super.initState();
    _loadWeights(_selectedBucket);
  }

  Future<void> _loadWeights(String bucket) async {
    setState(() {
      _loading = true;
      _error = null;
    });

    final data = await ApiService.getProfileWeights(bucket);

    if (!mounted) return;

    if (data.containsKey('error')) {
      setState(() {
        _error = 'Could not fetch weights: ${data['error']}';
        _loading = false;
      });
      return;
    }

    final rawBuckets = data['buckets'];
    final rawWeights = data['weights'];
    final rawDeltas  = data['user_deltas'];

    setState(() {
      _loading = false;
      _selectedBucket = bucket;

      if (rawBuckets is List) {
        _buckets = rawBuckets.cast<String>();
      }

      _weights = (rawWeights is Map)
          ? rawWeights
                .map((k, v) => MapEntry(k.toString(), _toInt(v)))
          : {};

      _deltas = (rawDeltas is Map)
          ? rawDeltas
                .map((k, v) => MapEntry(k.toString(), _toInt(v)))
          : {};
    });
  }

  Future<void> _sendFeedback(String concept, String label) async {
    setState(() => _pending[concept] = true);

    final ok = await ApiService.submitFeedback(concept: concept, label: label);

    if (!mounted) return;
    setState(() => _pending.remove(concept));

    if (ok) {
      // Optimistic local update so the UI reflects the change immediately
      // without waiting for a full re-fetch.
      final rate = 8; // LEARNING_RATE_MANUAL from backend
      final delta = label == 'PRODUCTIVE' ? rate : -rate;
      setState(() {
        final oldDelta = _deltas[concept] ?? 0;
        final newDelta = (oldDelta + delta).clamp(-40, 40);
        _deltas[concept] = newDelta;

        final base = _weights[concept] ?? 0;
        // Recompute: effective = (effective - old_delta) + new_delta
        final prevDelta = oldDelta;
        _weights[concept] = base - prevDelta + newDelta;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              label == 'PRODUCTIVE'
                  ? '👍 "$concept" marked productive'
                  : '👎 "$concept" marked distraction',
              style: GoogleFonts.inter(fontWeight: FontWeight.w600),
            ),
            backgroundColor: label == 'PRODUCTIVE'
                ? const Color(0xFF16A34A)
                : const Color(0xFFDC2626),
            duration: const Duration(seconds: 2),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    }
  }

  // ── Build ───────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        title: Text(
          'AI Profile & Weights',
          style: GoogleFonts.outfit(fontWeight: FontWeight.w800),
        ),
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_outlined),
            tooltip: 'Reload',
            onPressed: () => _loadWeights(_selectedBucket),
          ),
        ],
      ),
      body: Stack(
        children: [
          const AnimatedBackground(),
          SafeArea(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? _buildError()
                    : _buildContent(),
          ),
        ],
      ),
    );
  }

  Widget _buildError() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: GlassCard(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.warning_amber_outlined,
                  color: Color(0xFFF59E0B), size: 40),
              const SizedBox(height: 12),
              Text(
                _error!,
                style: GoogleFonts.inter(color: Colors.white70),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              PrimaryButton(
                label: 'Retry',
                onPressed: () => _loadWeights(_selectedBucket),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildContent() {
    return CustomScrollView(
      slivers: [
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          sliver: SliverToBoxAdapter(child: _buildHeader()),
        ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          sliver: SliverToBoxAdapter(child: _buildBucketChips()),
        ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
          sliver: SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                children: [
                  Text(
                    'HEURISTIC WEIGHTS',
                    style: GoogleFonts.jetBrainsMono(
                      color: Colors.white38,
                      fontSize: 11,
                      letterSpacing: 1.2,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${_weights.length} concepts',
                    style: GoogleFonts.jetBrainsMono(
                      color: Colors.white38,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          sliver: SliverList(
            delegate: SliverChildBuilderDelegate(
              (context, index) {
                final entry = _weights.entries.elementAt(index);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _WeightRow(
                    concept: entry.key,
                    effectiveWeight: entry.value,
                    userDelta: _deltas[entry.key] ?? 0,
                    isPending: _pending[entry.key] ?? false,
                    onThumbsUp: () =>
                        _sendFeedback(entry.key, 'PRODUCTIVE'),
                    onThumbsDown: () =>
                        _sendFeedback(entry.key, 'DISTRACTION'),
                  ),
                );
              },
              childCount: _weights.length,
            ),
          ),
        ),
        const SliverPadding(padding: EdgeInsets.only(bottom: 32)),
      ],
    );
  }

  Widget _buildHeader() {
    final learnedCount = _deltas.length;
    return GlassCard(
      padding: const EdgeInsets.all(20),
      child: Row(
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: const LinearGradient(
                colors: [Color(0xFF6643ED), Color(0xFF3B82F6)],
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF6643ED).withValues(alpha: 0.35),
                  blurRadius: 16,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: const Icon(Icons.psychology_outlined,
                color: Colors.white, size: 26),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Personalized Intelligence',
                  style: GoogleFonts.outfit(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  learnedCount == 0
                      ? 'No personalizations yet — using defaults'
                      : '$learnedCount concept${learnedCount == 1 ? '' : 's'} '
                          'personalized in $_selectedBucket',
                  style: GoogleFonts.inter(
                    color: Colors.white60,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBucketChips() {
    return SizedBox(
      height: 38,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: _buckets.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, index) {
          final bucket = _buckets[index];
          final selected = bucket == _selectedBucket;
          return GestureDetector(
            onTap: selected ? null : () => _loadWeights(bucket),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(99),
                color: selected
                    ? const Color(0xFF6643ED).withValues(alpha: 0.28)
                    : Colors.white.withValues(alpha: 0.06),
                border: Border.all(
                  color: selected
                      ? const Color(0xFF6643ED).withValues(alpha: 0.6)
                      : Colors.white.withValues(alpha: 0.10),
                ),
              ),
              child: Text(
                bucket,
                style: GoogleFonts.inter(
                  color: selected ? Colors.white : Colors.white60,
                  fontSize: 13,
                  fontWeight:
                      selected ? FontWeight.w700 : FontWeight.w500,
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  int _toInt(dynamic v) {
    if (v is int) return v;
    if (v is num) return v.toInt();
    return 0;
  }
}

// ── Weight Row Widget ──────────────────────────────────────────────────────────

class _WeightRow extends StatelessWidget {
  final String concept;
  final int effectiveWeight;
  final int userDelta;
  final bool isPending;
  final VoidCallback onThumbsUp;
  final VoidCallback onThumbsDown;

  const _WeightRow({
    required this.concept,
    required this.effectiveWeight,
    required this.userDelta,
    required this.isPending,
    required this.onThumbsUp,
    required this.onThumbsDown,
  });

  @override
  Widget build(BuildContext context) {
    final bool isPositive = effectiveWeight > 0;
    final bool isNegative = effectiveWeight < 0;
    final bool hasUserDelta = userDelta != 0;

    final Color barColor = isPositive
        ? const Color(0xFF4ADE80)
        : isNegative
            ? const Color(0xFFF87171)
            : Colors.white38;

    final double absMax = 60.0;
    final double barFraction = (effectiveWeight.abs() / absMax).clamp(0.0, 1.0);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.09)),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Colors.white.withValues(alpha: 0.07),
            Colors.white.withValues(alpha: 0.02),
          ],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              // Concept name
              Expanded(
                child: Text(
                  concept,
                  style: GoogleFonts.inter(
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),

              // User delta badge
              if (hasUserDelta) ...[
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(99),
                    color: userDelta > 0
                        ? const Color(0xFF16A34A).withValues(alpha: 0.20)
                        : const Color(0xFFDC2626).withValues(alpha: 0.20),
                  ),
                  child: Text(
                    '${userDelta > 0 ? '+' : ''}$userDelta',
                    style: GoogleFonts.jetBrainsMono(
                      fontSize: 10,
                      color: userDelta > 0
                          ? const Color(0xFF4ADE80)
                          : const Color(0xFFF87171),
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
              ],

              // Effective weight
              Text(
                '${effectiveWeight > 0 ? '+' : ''}$effectiveWeight',
                style: GoogleFonts.jetBrainsMono(
                  color: barColor,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),

              const SizedBox(width: 12),

              // Thumbs buttons
              if (isPending)
                const SizedBox(
                  width: 48,
                  height: 24,
                  child: Center(
                    child: SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  ),
                )
              else ...[
                _FeedbackButton(
                  icon: Icons.thumb_up_outlined,
                  color: const Color(0xFF4ADE80),
                  onTap: onThumbsUp,
                  tooltip: 'Mark productive',
                ),
                const SizedBox(width: 6),
                _FeedbackButton(
                  icon: Icons.thumb_down_outlined,
                  color: const Color(0xFFF87171),
                  onTap: onThumbsDown,
                  tooltip: 'Mark distraction',
                ),
              ],
            ],
          ),

          const SizedBox(height: 8),

          // Mini weight bar
          ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: LinearProgressIndicator(
              value: barFraction,
              minHeight: 4,
              backgroundColor: Colors.white.withValues(alpha: 0.07),
              valueColor: AlwaysStoppedAnimation<Color>(
                barColor.withValues(alpha: 0.7),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _FeedbackButton extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback onTap;
  final String tooltip;

  const _FeedbackButton({
    required this.icon,
    required this.color,
    required this.onTap,
    required this.tooltip,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          width: 30,
          height: 30,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: color.withValues(alpha: 0.12),
            border: Border.all(color: color.withValues(alpha: 0.30)),
          ),
          child: Icon(icon, size: 15, color: color),
        ),
      ),
    );
  }
}
