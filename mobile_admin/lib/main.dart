import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/customers.dart';
import 'screens/dashboard.dart';
import 'screens/ledger.dart';
import 'screens/orders.dart';
import 'screens/products.dart';
import 'screens/setup.dart';
import 'screens/support.dart';
import 'theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.instance.restore();
  runApp(const BackOfficeApp());
}

class BackOfficeApp extends StatelessWidget {
  const BackOfficeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Back Office',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: const Gate(),
    );
  }
}

/// Decides between the sign-in flow and the app.
///
/// Kept as a widget rather than a route so that a 401 anywhere can drop the
/// whole app back here in one call, instead of every screen having to know how
/// to unwind its own navigation stack.
class Gate extends StatefulWidget {
  const Gate({super.key});
  @override
  State<Gate> createState() => _GateState();
}

class _GateState extends State<Gate> {
  @override
  Widget build(BuildContext context) {
    final api = Api.instance;
    if (!api.isConfigured || !api.isSignedIn) {
      return SetupScreen(onDone: () => setState(() {}));
    }
    return Shell(onSignedOut: () => setState(() {}));
  }
}

/// The signed-in app: five destinations, the last a hub for the rest.
///
/// Five is the limit for a bottom bar before the labels stop being readable,
/// and the back office has seven modules. The four with the most daily traffic
/// get a tab; the others live behind "More". That split is by frequency of use,
/// not by importance — the ledger matters enormously and is opened weekly.
class Shell extends StatefulWidget {
  const Shell({super.key, required this.onSignedOut});
  final VoidCallback onSignedOut;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _index = 0;

  late final List<Widget> _screens = [
    const DashboardScreen(),
    const OrdersScreen(),
    const ProductsScreen(),
    const CustomersScreen(),
    MoreScreen(onSignedOut: widget.onSignedOut),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _index, children: _screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.dashboard_outlined),
              selectedIcon: Icon(Icons.dashboard),
              label: 'Home'),
          NavigationDestination(
              icon: Icon(Icons.receipt_long_outlined),
              selectedIcon: Icon(Icons.receipt_long),
              label: 'Orders'),
          NavigationDestination(
              icon: Icon(Icons.inventory_2_outlined),
              selectedIcon: Icon(Icons.inventory_2),
              label: 'Products'),
          NavigationDestination(
              icon: Icon(Icons.people_outline),
              selectedIcon: Icon(Icons.people),
              label: 'Customers'),
          NavigationDestination(
              icon: Icon(Icons.more_horiz),
              label: 'More'),
        ],
      ),
    );
  }
}

/// Everything that does not earn a tab.
class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key, required this.onSignedOut});
  final VoidCallback onSignedOut;

  @override
  Widget build(BuildContext context) {
    final api = Api.instance;
    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: ListTile(
              leading: const CircleAvatar(
                backgroundColor: Brand.ink,
                child: Icon(Icons.person, color: Colors.white, size: 20),
              ),
              title: Text(api.username ?? 'Signed in',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
              subtitle: Text(api.baseUrl ?? '',
                  maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
          ),
          const SizedBox(height: 16),
          _Tile(
            icon: Icons.account_balance_wallet_outlined,
            title: 'Khata (Ledger)',
            subtitle: 'Balances and payments',
            onTap: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => const LedgerScreen())),
          ),
          _Tile(
            icon: Icons.support_agent_outlined,
            title: 'Support tickets',
            subtitle: 'Read and reply',
            onTap: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => const SupportScreen())),
          ),
          _Tile(
            icon: Icons.inbox_outlined,
            title: 'Product requests',
            subtitle: 'Sourcing enquiries from the website',
            onTap: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => const ProductRequestsScreen())),
          ),
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(Icons.logout, color: Brand.danger),
              title: const Text('Sign out',
                  style: TextStyle(color: Brand.danger, fontWeight: FontWeight.w600)),
              onTap: () async {
                final confirmed = await showDialog<bool>(
                  context: context,
                  builder: (c) => AlertDialog(
                    title: const Text('Sign out?'),
                    content: const Text(
                        'You will need your password to sign back in.'),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(c, false),
                          child: const Text('Cancel')),
                      FilledButton(
                          onPressed: () => Navigator.pop(c, true),
                          child: const Text('Sign out')),
                    ],
                  ),
                );
                if (confirmed != true) return;
                await api.signOut();
                onSignedOut();
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: ListTile(
          leading: Icon(icon, color: Brand.goldText),
          title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text(subtitle, style: const TextStyle(fontSize: 12.5)),
          trailing: const Icon(Icons.chevron_right, color: Brand.muted),
          onTap: onTap,
        ),
      ),
    );
  }
}
