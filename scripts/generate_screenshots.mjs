// scripts/generate_screenshots.mjs
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { spawn } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');
const DIST_DIR = path.resolve(ROOT_DIR, 'frontend', 'dist');
const SCREENSHOTS_DIR = path.resolve(ROOT_DIR, 'docs', 'screenshots');

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

// MIME types for static server
const MIME_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
};

const MOCK_DATA = {
  USER: {
    me: {
      user_id: 'usr_alex_mercer',
      email: 'alex.mercer@gympro.io',
      full_name: 'Alex Mercer',
      role: 'USER',
      account_status: 'ACTIVE',
      email_verified: true,
      created_at: '2026-01-10T10:00:00Z',
    },
    membership: {
      plan_id: 'plan_gold',
      plan_name: 'Gold All-Access',
      status: 'ACTIVE',
      renews_at: '2026-11-20T00:00:00Z',
      price_inr: 1999,
      features: ['Unlimited Gym Access', 'All Group Classes', 'AI Coach Priority', 'Locker & Towel Service'],
    },
    classes: [
      {
        id: 'cls_hiit_1',
        title: 'HIIT Athletic Conditioning',
        trainer_name: 'Sarah Connor',
        starts_at: new Date(Date.now() + 86400000).toISOString(),
        ends_at: new Date(Date.now() + 90000000).toISOString(),
        capacity: 20,
        booked_count: 14,
        room: 'Studio A',
        status: 'SCHEDULED',
      },
      {
        id: 'cls_yoga_1',
        title: 'Vinyasa Mobility & Flow',
        trainer_name: 'Elena Rostova',
        starts_at: new Date(Date.now() + 100000000).toISOString(),
        ends_at: new Date(Date.now() + 103600000).toISOString(),
        capacity: 15,
        booked_count: 8,
        room: 'Mind-Body Studio',
        status: 'SCHEDULED',
      },
      {
        id: 'cls_str_1',
        title: 'Heavy Barbell Strength',
        trainer_name: 'Marcus Stone',
        starts_at: new Date(Date.now() + 120000000).toISOString(),
        ends_at: new Date(Date.now() + 123600000).toISOString(),
        capacity: 12,
        booked_count: 12,
        room: 'Weight Deck',
        status: 'SCHEDULED',
      },
    ],
    bookings: [
      {
        id: 'bk_1',
        class_id: 'cls_hiit_1',
        class_title: 'HIIT Athletic Conditioning',
        trainer_name: 'Sarah Connor',
        starts_at: new Date(Date.now() + 86400000).toISOString(),
        status: 'CONFIRMED',
      },
    ],
  },
  TRAINER: {
    me: {
      user_id: 'usr_sarah_connor',
      email: 'sarah.connor@gympro.io',
      full_name: 'Sarah Connor',
      role: 'TRAINER',
      account_status: 'ACTIVE',
      email_verified: true,
      created_at: '2026-01-05T08:00:00Z',
    },
    classes: [
      {
        id: 'cls_hiit_1',
        title: 'HIIT Athletic Conditioning',
        category: 'HIIT',
        start_time: new Date(Date.now() + 86400000).toISOString(),
        end_time: new Date(Date.now() + 90000000).toISOString(),
        capacity: 20,
        booked_count: 14,
        status: 'SCHEDULED',
      },
      {
        id: 'cls_hiit_2',
        title: 'Power Intervals',
        category: 'HIIT',
        start_time: new Date(Date.now() + 172800000).toISOString(),
        end_time: new Date(Date.now() + 176400000).toISOString(),
        capacity: 15,
        booked_count: 12,
        status: 'SCHEDULED',
      },
    ],
    roster: [
      { booking_id: 'b1', first_name: 'Alex', attendance_status: 'CONFIRMED' },
      { booking_id: 'b2', first_name: 'Jordan', attendance_status: 'CONFIRMED' },
      { booking_id: 'b3', first_name: 'Taylor', attendance_status: 'CONFIRMED' },
      { booking_id: 'b4', first_name: 'Maya', attendance_status: 'CONFIRMED' },
    ],
  },
  ADMIN: {
    me: {
      user_id: 'usr_admin_elena',
      email: 'admin@gympro.io',
      full_name: 'Elena Rostova (Admin)',
      role: 'ADMIN',
      account_status: 'ACTIVE',
      email_verified: true,
      created_at: '2025-12-01T00:00:00Z',
    },
    metrics: {
      total_active_members: 1420,
      active_subscriptions_inr: 2845000,
      today_attendance: 312,
      open_disputes: 2,
    },
    approvals: [
      {
        id: 'req_1',
        user_name: 'David Miller',
        requested_role: 'TRAINER',
        submitted_at: '2026-10-18T14:00:00Z',
        status: 'PENDING',
      },
      {
        id: 'req_2',
        user_name: 'Samantha Ray',
        requested_role: 'TRAINER',
        submitted_at: '2026-10-18T15:30:00Z',
        status: 'PENDING',
      },
    ],
    issues: [
      {
        id: 'iss_1',
        member_name: 'Member #1042',
        summary: 'Treadmill #4 emergency belt slip',
        priority: 'HIGH',
        status: 'OPEN',
      },
      {
        id: 'iss_2',
        member_name: 'Member #1189',
        summary: 'Water dispenser filter replacement',
        priority: 'LOW',
        status: 'OPEN',
      },
    ],
  },
};

let activeTargetRole = 'USER';

const server = http.createServer((req, res) => {
  const parsedUrl = new URL(req.url, 'http://localhost:5173');
  const pathname = parsedUrl.pathname;

  // Track role if explicitly in query
  const qRole = parsedUrl.searchParams.get('role');
  if (qRole) {
    activeTargetRole = qRole;
  }
  const role = activeTargetRole;

  // API Interception
  if (pathname.startsWith('/api/')) {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Access-Control-Allow-Origin', '*');
    const mock = MOCK_DATA[role] || MOCK_DATA.USER;

    if (pathname === '/api/me') {
      res.writeHead(200);
      res.end(JSON.stringify(mock.me));
      return;
    }
    if (pathname === '/api/classes') {
      res.writeHead(200);
      res.end(JSON.stringify(mock.classes || []));
      return;
    }
    if (pathname === '/api/bookings' || pathname === '/api/me/bookings') {
      res.writeHead(200);
      res.end(JSON.stringify(mock.bookings || []));
      return;
    }
    if (pathname === '/api/membership' || pathname === '/api/me/membership') {
      res.writeHead(200);
      res.end(JSON.stringify(mock.membership || {}));
      return;
    }
    if (pathname === '/api/plans') {
      res.writeHead(200);
      res.end(
        JSON.stringify([
          { id: 'plan_silver', name: 'Silver Basic', price_inr: 999, billing_cycle: 'MONTHLY' },
          { id: 'plan_gold', name: 'Gold All-Access', price_inr: 1999, billing_cycle: 'MONTHLY' },
          { id: 'plan_plat', name: 'Platinum VIP', price_inr: 3499, billing_cycle: 'MONTHLY' },
        ])
      );
      return;
    }
    if (pathname.startsWith('/api/trainer/classes')) {
      res.writeHead(200);
      res.end(JSON.stringify(MOCK_DATA.TRAINER.classes));
      return;
    }
    if (pathname.startsWith('/api/trainer/roster')) {
      res.writeHead(200);
      res.end(JSON.stringify(MOCK_DATA.TRAINER.roster));
      return;
    }
    if (pathname.startsWith('/api/admin/overview')) {
      res.writeHead(200);
      res.end(JSON.stringify({
        active_members: 1420,
        mrr: 2845000.0,
        occupancy_rate: 68.4,
        trials_converted: 74.2,
        no_show_rate: 4.8,
        churn_rate: 2.1,
        open_issues: 3,
      }));
      return;
    }
    if (pathname.startsWith('/api/admin/trainer-requests')) {
      res.writeHead(200);
      res.end(JSON.stringify(MOCK_DATA.ADMIN.approvals));
      return;
    }
    if (pathname.startsWith('/api/admin/admin-requests')) {
      res.writeHead(200);
      res.end(JSON.stringify([]));
      return;
    }
    if (pathname.startsWith('/api/admin/issues')) {
      res.writeHead(200);
      res.end(JSON.stringify(MOCK_DATA.ADMIN.issues));
      return;
    }

    res.writeHead(200);
    res.end(JSON.stringify({ ok: true, data: [] }));
    return;
  }

  // Static files from frontend/dist
  let filePath = path.join(DIST_DIR, pathname === '/' ? 'index.html' : pathname);
  let isHtml = false;
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(DIST_DIR, 'index.html');
    isHtml = true;
  } else if (pathname.endsWith('.html') || pathname === '/') {
    isHtml = true;
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.readFile(filePath, isHtml ? 'utf8' : null, (err, data) => {
    if (err) {
      res.writeHead(500);
      res.end('Error loading file');
      return;
    }

    if (isHtml) {
      // Inject bootstrap script into head
      const injection = `
      <script>
        (function() {
          var params = new URLSearchParams(window.location.search);
          var r = params.get('role');
          var t = params.get('theme') || 'light';
          var c = params.get('coach') === '1';

          if (r) {
            localStorage.setItem('gympro_access_token', 'mock_token_' + r);
          }
          if (t === 'dark') {
            document.documentElement.classList.add('dark');
            localStorage.setItem('gympro_theme', 'dark');
          } else {
            document.documentElement.classList.remove('dark');
            localStorage.setItem('gympro_theme', 'light');
          }

          if (c) {
            window.addEventListener('load', function() {
              setTimeout(function() {
                var btns = Array.from(document.querySelectorAll('button'));
                var coachBtn = btns.find(function(b) { return b.textContent && b.textContent.includes('Coach'); });
                if (coachBtn) {
                  coachBtn.click();
                  // Prepopulate simulated coach conversation
                  setTimeout(function() {
                    var input = document.querySelector('textarea, input[placeholder*=\"Coach\"]');
                    if (input) input.value = "What is the best routine for strength without knee strain?";
                  }, 300);
                }
              }, 400);
            });
          }
        })();
      </script>
      `;
      const modifiedHtml = data.replace('</head>', `${injection}\n</head>`);
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(modifiedHtml);
      return;
    }

    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
});

const PORT = 5173;
server.listen(PORT, async () => {
  console.log(`Screenshot server active at http://localhost:${PORT}`);

  const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
  const userDataDir = path.resolve(ROOT_DIR, '.tmp_edge_profile');

  const targets = [
    {
      name: 'landing_desktop_light.png',
      url: `http://localhost:${PORT}/?theme=light`,
      width: 1280,
      height: 800,
      wait: 2500,
    },
    {
      name: 'landing_mobile_dark.png',
      url: `http://localhost:${PORT}/?theme=dark`,
      width: 390,
      height: 844,
      wait: 2500,
    },
    {
      name: 'member_dashboard_desktop_light.png',
      url: `http://localhost:${PORT}/app?role=USER&theme=light`,
      width: 1280,
      height: 800,
      wait: 3000,
    },
    {
      name: 'member_dashboard_mobile_dark.png',
      url: `http://localhost:${PORT}/app?role=USER&theme=dark`,
      width: 390,
      height: 844,
      wait: 3000,
    },
    {
      name: 'coach_drawer_mobile.png',
      url: `http://localhost:${PORT}/app?role=USER&theme=dark&coach=1`,
      width: 390,
      height: 844,
      wait: 3500,
    },
    {
      name: 'membership_desktop_light.png',
      url: `http://localhost:${PORT}/app/membership?role=USER&theme=light`,
      width: 1280,
      height: 800,
      wait: 3000,
    },
    {
      name: 'trainer_console_desktop.png',
      url: `http://localhost:${PORT}/trainer?role=TRAINER&theme=light`,
      width: 1280,
      height: 800,
      wait: 3000,
    },
    {
      name: 'admin_console_desktop.png',
      url: `http://localhost:${PORT}/admin?role=ADMIN&theme=dark`,
      width: 1280,
      height: 800,
      wait: 3000,
    },
  ];

  for (const t of targets) {
    const outPath = path.join(SCREENSHOTS_DIR, t.name);
    console.log(`Capturing ${t.name} (${t.width}x${t.height})...`);
    
    // Set active server role for this target
    if (t.url.includes('role=TRAINER')) activeTargetRole = 'TRAINER';
    else if (t.url.includes('role=ADMIN')) activeTargetRole = 'ADMIN';
    else activeTargetRole = 'USER';

    const targetUserDir = path.resolve(ROOT_DIR, '.tmp_edge_' + t.name.replace(/[^a-zA-Z0-9]/g, '_'));

    await new Promise((resolve) => {
      const child = spawn(
        edgePath,
        [
          '--headless=new',
          `--user-data-dir=${targetUserDir}`,
          '--disable-gpu',
          `--window-size=${t.width},${t.height}`,
          `--virtual-time-budget=${t.wait}`,
          `--screenshot=${outPath}`,
          t.url,
        ],
        { stdio: 'inherit' }
      );
      child.on('exit', () => {
        resolve();
      });
    });
  }

  console.log('All screenshots captured successfully!');
  server.close(() => {
    process.exit(0);
  });
});
