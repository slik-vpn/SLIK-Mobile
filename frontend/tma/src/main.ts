import "./styles.css";

type TelegramUser = {
  id?: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  language_code?: string;
};

type TelegramWebApp = {
  initDataUnsafe?: {
    user?: TelegramUser;
  };
  ready?: () => void;
  expand?: () => void;
  showAlert?: (message: string) => void;
  openTelegramLink?: (url: string) => void;
};

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

type PageKey = "home" | "referral" | "profile";

type NavItem = {
  key: PageKey;
  label: string;
  icon: string;
};

const navItems: NavItem[] = [
  { key: "home", label: "Главная", icon: "🏠" },
  { key: "referral", label: "Рефералка", icon: "👥" },
  { key: "profile", label: "Профиль", icon: "👤" },
];

const mockProfile = {
  balance: "$12.50",
  cashback: "$4.80",
  status: "Explorer",
  statusPair: "Traveller / Explorer",
  nextStatus: "Nomad",
  remainingToNomad: "$18",
  progress: 58,
};

const mockReferralStats = [
  { label: "Переходов", value: "127" },
  { label: "Купили", value: "18" },
  { label: "Не купили", value: "109" },
  { label: "Бонусов начислено", value: "$42.50" },
];

const app = document.querySelector<HTMLDivElement>("#app");
const telegramApp = window.Telegram?.WebApp;

telegramApp?.ready?.();
telegramApp?.expand?.();

let activePage: PageKey = "home";

function displayName(user?: TelegramUser): string {
  if (!user) {
    return "Гость";
  }

  const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
  return fullName || (user.username ? `@${user.username}` : "Пользователь Telegram");
}

function userName(user?: TelegramUser): string {
  return user?.username ? `@${user.username}` : "Не указан";
}

function alertMessage(message: string): void {
  if (telegramApp?.showAlert) {
    telegramApp.showAlert(message);
    return;
  }

  window.alert(message);
}

function shareReferralLink(): void {
  const referralUrl = "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fslik_mobile_bot%3Fstart%3Dref_mock&text=SLIK%20Mobile%20eSIM%20для%20путешествий";

  if (telegramApp?.openTelegramLink) {
    telegramApp.openTelegramLink(referralUrl);
    return;
  }

  alertMessage("Ссылка для друзей: https://t.me/slik_mobile_bot?start=ref_mock");
}

function showSoonMessage(): void {
  alertMessage("Скоро в приложении");
}

function renderHome(user?: TelegramUser): string {
  return `
    <section class="hero-panel">
      <div class="hero-copy">
        <span class="eyebrow">SLIK Mobile TMA</span>
        <h1>Привет, ${displayName(user)}!</h1>
        <p>Управляйте путешествиями, бонусами и профилем в Telegram Mini App.</p>
      </div>
      <div class="globe-orbit" aria-hidden="true">🌍</div>
    </section>

    <section class="slik-card feature-card">
      <div>
        <span class="label">SLIK Mobile</span>
        <h2>Интернет по всему миру</h2>
        <p>200+ стран</p>
      </div>
      <span class="pill">eSIM</span>
    </section>

    <section class="stats-row" aria-label="Баланс и статус">
      <article class="mini-card">
        <span class="label">SLIK Balance</span>
        <strong>${mockProfile.balance}</strong>
      </article>
      <article class="mini-card">
        <span class="label">Статус</span>
        <strong>${mockProfile.statusPair}</strong>
      </article>
    </section>

    <button class="primary-action" type="button" data-action="buy-esim">🌍 Купить eSIM</button>

    <section class="quick-grid" aria-label="Быстрые действия">
      <button class="quick-card" type="button" data-action="orders-stub">
        <span>📦</span>
        <strong>Мои заказы</strong>
      </button>
      <button class="quick-card" type="button" data-page="referral">
        <span>👥</span>
        <strong>Рефералка</strong>
      </button>
      <button class="quick-card" type="button" data-page="profile">
        <span>👤</span>
        <strong>Профиль</strong>
      </button>
    </section>
  `;
}

function renderReferral(): string {
  return `
    <section class="screen-card referral-hero">
      <span class="screen-icon">👥</span>
      <h1>Приглашай друзей</h1>
      <p>Делитесь ссылкой и получайте бонусы за покупки друзей</p>
    </section>

    <section class="referral-stats" aria-label="Статистика рефералки">
      ${mockReferralStats
        .map(
          (stat) => `
            <article class="stat-card">
              <span>${stat.label}</span>
              <strong>${stat.value}</strong>
            </article>
          `,
        )
        .join("")}
    </section>

    <button class="primary-action" type="button" data-action="share-referral">📤 Поделиться ссылкой</button>
  `;
}

function renderProfile(user?: TelegramUser): string {
  return `
    <section class="profile-card">
      <div class="avatar">${displayName(user).slice(0, 1).toUpperCase()}</div>
      <div>
        <span class="label">Профиль</span>
        <h1>${displayName(user)}</h1>
        <p>${mockProfile.status} traveller</p>
      </div>
    </section>

    <section class="details-list" aria-label="Данные профиля">
      <div><span>Telegram ID</span><strong>${user?.id ?? "Недоступен"}</strong></div>
      <div><span>Username</span><strong>${userName(user)}</strong></div>
      <div><span>Статус путешественника</span><strong>${mockProfile.status}</strong></div>
      <div><span>SLIK Balance</span><strong>${mockProfile.balance}</strong></div>
      <div><span>Cashback</span><strong>${mockProfile.cashback}</strong></div>
    </section>

    <section class="progress-card">
      <div class="progress-header">
        <div>
          <span class="label">Прогресс статуса</span>
          <h2>${mockProfile.status}</h2>
        </div>
        <span class="pill">${mockProfile.progress}%</span>
      </div>
      <div class="progress-track" aria-label="Прогресс до Nomad" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${mockProfile.progress}" role="progressbar">
        <span style="width: ${mockProfile.progress}%"></span>
      </div>
      <p>До ${mockProfile.nextStatus} осталось ${mockProfile.remainingToNomad}</p>
    </section>
  `;
}

function renderPage(user?: TelegramUser): string {
  switch (activePage) {
    case "referral":
      return renderReferral();
    case "profile":
      return renderProfile(user);
    case "home":
    default:
      return renderHome(user);
  }
}

function bindActions(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      activePage = button.dataset.page as PageKey;
      render();
    });
  });

  document.querySelector<HTMLButtonElement>("[data-action='buy-esim']")?.addEventListener("click", showSoonMessage);
  document.querySelector<HTMLButtonElement>("[data-action='orders-stub']")?.addEventListener("click", () => alertMessage("Мои заказы скоро появятся в приложении"));
  document.querySelector<HTMLButtonElement>("[data-action='share-referral']")?.addEventListener("click", shareReferralLink);
}

function render(): void {
  if (!app) {
    return;
  }

  const user = telegramApp?.initDataUnsafe?.user;

  app.innerHTML = `
    <main class="app-shell">
      <header class="top-bar">
        <div class="brand-mark">S</div>
        <div>
          <div class="brand-title">SLIK Mobile</div>
          <div class="brand-subtitle">Premium eSIM club</div>
        </div>
      </header>
      <div class="content">${renderPage(user)}</div>
    </main>
    <nav class="bottom-nav" aria-label="Основная навигация">
      ${navItems
        .map(
          (item) => `
            <button class="nav-button ${item.key === activePage ? "active" : ""}" data-page="${item.key}" type="button" aria-current="${item.key === activePage ? "page" : "false"}">
              <span>${item.icon}</span>
              <span>${item.label}</span>
            </button>
          `,
        )
        .join("")}
    </nav>
  `;

  bindActions();
}

render();
