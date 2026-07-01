export const formatName = (firstName?: string | null, lastName?: string | null, username?: string | null) => {
  const fullName = [firstName, lastName].filter(Boolean).join(' ').trim();
  return fullName || (username ? `@${username}` : 'Не указано');
};
