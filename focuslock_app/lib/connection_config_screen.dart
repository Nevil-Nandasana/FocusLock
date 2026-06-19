import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';

import 'providers.dart';
import 'ui_components.dart';

/// Screen for configuring the Windows FocusLock host URL.
/// Accessible from the connection banner on the dashboard.
class ConnectionConfigScreen extends ConsumerStatefulWidget {
  const ConnectionConfigScreen({super.key});

  @override
  ConsumerState<ConnectionConfigScreen> createState() =>
      _ConnectionConfigScreenState();
}

class _ConnectionConfigScreenState
    extends ConsumerState<ConnectionConfigScreen> {
  late TextEditingController _urlController;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    final conn = ref.read(connectionProvider).valueOrNull;
    _urlController = TextEditingController(
      text: conn?.hostUrl ?? 'http://127.0.0.1:5000/api',
    );
  }

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final url = _urlController.text.trim();
    if (url.isEmpty) return;
    setState(() => _isSaving = true);
    await ref.read(connectionProvider.notifier).setHost(url);
    setState(() => _isSaving = false);
    if (!mounted) return;
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        title: Text(
          'Host Configuration',
          style: GoogleFonts.outfit(fontWeight: FontWeight.bold),
        ),
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: Stack(
        children: [
          const AnimatedBackground(),
          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(
                  horizontal: 24,
                  vertical: 16,
                ),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 480),
                  child: GlassCard(
                    padding: const EdgeInsets.all(28),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        // Icon
                        Container(
                          width: 64,
                          height: 64,
                          margin: const EdgeInsets.only(bottom: 20),
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: const LinearGradient(
                              colors: [Color(0xFF6643ED), Color(0xFF3B82F6)],
                            ),
                            boxShadow: [
                              BoxShadow(
                                color:
                                    const Color(0xFF6643ED).withValues(alpha: 0.35),
                                blurRadius: 20,
                                offset: const Offset(0, 6),
                              ),
                            ],
                          ),
                          child: const Icon(
                            Icons.computer_outlined,
                            color: Colors.white,
                            size: 32,
                          ),
                        ),

                        Text(
                          'Windows Host',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.outfit(
                            fontSize: 28,
                            fontWeight: FontWeight.w800,
                            color: Colors.white,
                          ),
                        ),
                        const SizedBox(height: 10),
                        Text(
                          'FocusLock monitoring runs on Windows only.\n'
                          'Enter the IP address of the machine running\n'
                          'the FocusLock backend.',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.inter(
                            color: Colors.white60,
                            height: 1.55,
                            fontSize: 13,
                          ),
                        ),
                        const SizedBox(height: 28),

                        // Host URL field
                        _fieldLabel('Backend URL'),
                        const SizedBox(height: 8),
                        _glassField(
                          child: TextField(
                            controller: _urlController,
                            style: GoogleFonts.jetBrainsMono(
                              color: Colors.white,
                              fontSize: 13,
                            ),
                            decoration: InputDecoration(
                              border: InputBorder.none,
                              hintText: 'http://192.168.1.x:5000/api',
                              hintStyle: GoogleFonts.jetBrainsMono(
                                color: Colors.white38,
                                fontSize: 13,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),

                        // Quick-fill presets
                        Text(
                          'Quick presets',
                          style: GoogleFonts.inter(
                            color: Colors.white54,
                            fontSize: 11,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          runSpacing: 6,
                          children: [
                            _preset('Localhost', 'http://127.0.0.1:5000/api'),
                            _preset(
                                'Android emulator', 'http://10.0.2.2:5000/api'),
                          ],
                        ),

                        const SizedBox(height: 28),

                        PrimaryButton(
                          label: _isSaving ? 'Probing host…' : 'SAVE & CONNECT',
                          onPressed: _isSaving ? null : _save,
                        ),
                        const SizedBox(height: 12),
                        PrimaryButton(
                          label: 'Cancel',
                          isSecondary: true,
                          onPressed: () => Navigator.pop(context),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _fieldLabel(String text) {
    return Text(
      text,
      style: GoogleFonts.inter(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        color: Colors.white70,
        letterSpacing: 0.5,
      ),
    );
  }

  Widget _glassField({required Widget child}) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.14)),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Colors.white.withValues(alpha: 0.08),
            Colors.white.withValues(alpha: 0.03),
          ],
        ),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
      child: child,
    );
  }

  Widget _preset(String label, String url) {
    return GestureDetector(
      onTap: () => _urlController.text = url,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: const Color(0xFF6643ED).withValues(alpha: 0.45)),
          color: const Color(0xFF6643ED).withValues(alpha: 0.12),
        ),
        child: Text(
          label,
          style: GoogleFonts.inter(
            color: const Color(0xFF8E8CFF),
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
