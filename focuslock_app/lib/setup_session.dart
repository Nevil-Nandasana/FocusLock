import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'ui_components.dart';
import 'api_service.dart';

class SetupSessionScreen extends StatefulWidget {
  const SetupSessionScreen({super.key});

  @override
  State<SetupSessionScreen> createState() => _SetupSessionScreenState();
}

class _SetupSessionScreenState extends State<SetupSessionScreen> {
  double _duration = 25;
  String _selectedCategory = 'Coding';
  String _selectedMode = 'deep';
  final TextEditingController _whitelistController = TextEditingController();
  final TextEditingController _blacklistController = TextEditingController();

  final List<String> categories = [
    'Studying', 'Coding', 'Interview Preparation', 'Research', 
    'Writing', 'Reading', 'Learning Course', 'Work Task', 'Deep Work'
  ];

  @override
  void dispose() {
    _whitelistController.dispose();
    _blacklistController.dispose();
    super.dispose();
  }

  void _startSession() async {
    final whitelist = _whitelistController.text.split(',')
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();
    final blacklist = _blacklistController.text
        .split(',')
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (c) => const Center(child: CircularProgressIndicator()),
    );

    final success = await ApiService.startSession(
      duration: _duration.toInt(),
      mode: _selectedMode,
      intent: _selectedCategory,
      whitelist: whitelist,
      blacklist: blacklist,
    );

    if (!mounted) return;
    Navigator.pop(context); // close dialog

    if (success) {
      Navigator.pop(context); // back to main which will auto-route to active session
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Failed to start session')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        title: Text('Setup Session', style: GoogleFonts.outfit(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: Stack(
        children: [
          const AnimatedBackground(),
          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Set Duration',
                    style: GoogleFonts.inter(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                  ),
                  const SizedBox(height: 16),
                  GlassCard(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        Text(
                          '${_duration.toInt()} min',
                          style: GoogleFonts.outfit(fontSize: 48, fontWeight: FontWeight.bold, color: const Color(0xFF6366F1)),
                        ),
                        Slider(
                          value: _duration,
                          min: 5,
                          max: 120,
                          divisions: 23,
                          activeColor: const Color(0xFF6366F1),
                          inactiveColor: Colors.white24,
                          onChanged: (val) {
                            setState(() {
                              _duration = val;
                            });
                          },
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 32),
                  Text(
                    'Select Category',
                    style: GoogleFonts.inter(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                  ),
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: categories.map((cat) {
                      final isSelected = _selectedCategory == cat;
                      return ChoiceChip(
                        label: Text(cat, style: GoogleFonts.inter(color: isSelected ? Colors.white : Colors.white70)),
                        selected: isSelected,
                        selectedColor: const Color(0xFF6366F1),
                        backgroundColor: Colors.white12,
                        onSelected: (bool selected) {
                          if (selected) setState(() => _selectedCategory = cat);
                        },
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: 32),
                  Text(
                    'Session Mode',
                    style: GoogleFonts.inter(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: ChoiceChip(
                          label: Text('Deep', style: GoogleFonts.inter(color: _selectedMode == 'deep' ? Colors.white : Colors.white70)),
                          selected: _selectedMode == 'deep',
                          selectedColor: const Color(0xFF6366F1),
                          backgroundColor: Colors.white12,
                          onSelected: (selected) {
                            if (selected) {
                              setState(() => _selectedMode = 'deep');
                            }
                          },
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: ChoiceChip(
                          label: Text('Standard', style: GoogleFonts.inter(color: _selectedMode == 'standard' ? Colors.white : Colors.white70)),
                          selected: _selectedMode == 'standard',
                          selectedColor: const Color(0xFF6366F1),
                          backgroundColor: Colors.white12,
                          onSelected: (selected) {
                            if (selected) {
                              setState(() => _selectedMode = 'standard');
                            }
                          },
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 32),
                  Text(
                    'Whitelist Keywords (optional)',
                    style: GoogleFonts.inter(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                  ),
                  const SizedBox(height: 16),
                  GlassCard(
                    padding: const EdgeInsets.all(8),
                    child: TextField(
                      controller: _whitelistController,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'e.g., stackoverflow, docs, github',
                        hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.5)),
                        border: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    'Blacklist Keywords (optional)',
                    style: GoogleFonts.inter(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                  ),
                  const SizedBox(height: 16),
                  GlassCard(
                    padding: const EdgeInsets.all(8),
                    child: TextField(
                      controller: _blacklistController,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'e.g., instagram, reels, shopping',
                        hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.5)),
                        border: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 48),
                  PrimaryButton(
                    label: 'Start Session',
                    onPressed: _startSession,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
