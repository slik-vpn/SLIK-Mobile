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
};

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

type PageKey = "home" | "orders" | "balance" | "referral" | "profile";

type NavItem = {
  key: PageKey;
  label: string;
  icon: string;
};

const navItems: NavItem[] = [
  { key: "home", label: "Главная", icon: "🏠" },
  { key: "orders", label: "Заказы", icon: "📦" },
  { key: "balance", label: "Баланс", icon: "💰" },
  { key: "referral", label: "Рефералка", icon: "👥" },
  { key: "profile", label: "Профиль", icon: "👤" },
];

const sectionCards = [
  { title: "Купить eSIM", text: "Скоро здесь появится быстрый выбор стран и тарифов.", icon: "🌍" },
  { title: "Мои заказы", text: "История и статусы заказов останутся в боте до следующих этапов TMA.", icon: "📦" },
  { title: "SLIK Balance", text: "Баланс, cashback и статусы будут подключены отдельным API позже.", icon: "💰" },
  { title: "Реферальная программа", text: "Реферальные ссылки и бонусы пока доступны в Telegram-боте.", icon: "👥" },
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

function renderHome(user?: TelegramUser): string {
  return `
    <section class="hero-card">
      <div class="eyebrow">Telegram Mini App</div>
      <h1>Добро пожаловать в SLIK Mobile</h1>
      <p>Базовое приложение уже готово. Покупка eSIM, оплаты и CRM остаются в текущем боте.</p>
    </section>

    <section class="user-card">
      <div>
        <span class="label">Имя пользователя</span>
        <strong>${displayName(user)}</strong>
      </div>
      <div>
        <span class="label">Telegram ID</span>
        <strong>${user?.id ?? "Недоступен"}</strong>
      </div>
    </section>

    <section class="card-grid" aria-label="Основные разделы">
      ${sectionCards
        .map(
          (card) => `
            <article class="section-card">
              <span class="section-icon">${card.icon}</span>
              <h2>${card.title}</h2>
              <p>${card.text}</p>
            </article>
          `,
        )
        .join("")}
    </section>
  `;
}

function renderPlaceholder(title: string, icon: string, text: string): string {
  return `
    <section class="placeholder-card">
      <span class="placeholder-icon">${icon}</span>
      <h1>${title}</h1>
      <p>${text}</p>
      <p class="muted">Это foundation-экран без переноса бизнес-логики. Данные будут подключены в следующих версиях.</p>
    </section>
  `;
}

function renderPage(user?: TelegramUser): string {
  switch (activePage) {
    case "orders":
      return renderPlaceholder("Заказы", "📦", "Здесь появятся ваши заказы и статусы eSIM.");
    case "balance":
      return renderPlaceholder("Баланс", "💰", "Здесь появится SLIK Balance, cashback и история начислений.");
    case "referral":
      return renderPlaceholder("Рефералка", "👥", "Здесь появится реферальная ссылка и бонусы за друзей.");
    case "profile":
      return renderPlaceholder("Профиль", "👤", "Здесь появятся профиль, Telegram-данные и настройки клиента.");
    case "home":
    default:
      return renderHome(user);
  }
}

function render(): void {
  if (!app) {
    return;
  }

  const user = telegramApp?.initDataUnsafe?.user;

  app.innerHTML = `
    <main class="shell">
      <div class="brand-row">
        <div class="brand-mark">S</div>
        <div>
          <div class="brand-title">SLIK Mobile</div>
          <div class="brand-subtitle">eSIM для путешествий</div>
        </div>
      </div>
      <div class="content">${renderPage(user)}</div>
    </main>
    <nav class="bottom-nav" aria-label="Основная навигация">
      ${navItems
        .map(
          (item) => `
            <button class="nav-button ${item.key === activePage ? "active" : ""}" data-page="${item.key}" type="button">
              <span>${item.icon}</span>
              <span>${item.label}</span>
            </button>
          `,
        )
        .join("")}
    </nav>
  `;

  document.querySelectorAll<HTMLButtonElement>("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      activePage = button.dataset.page as PageKey;
      render();
    });
  });
}

render();
