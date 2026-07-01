import { Markup } from 'telegraf';
import { Role } from '@prisma/client';

const ownerMenu = ['Сотрудники', 'Смены', 'Финансы', 'Задачи', 'Инциденты', 'Лента событий'];
const managerMenu = ['Мои смены', 'Моя зарплата', 'Задачи', 'Инциденты'];
const employeeMenu = ['Мои смены', 'Моя зарплата'];

export const getMainMenu = (role: Role) => {
  const items = role === Role.OWNER ? ownerMenu : role === Role.MANAGER ? managerMenu : employeeMenu;
  return Markup.keyboard(items.map((item) => [item])).resize();
};
