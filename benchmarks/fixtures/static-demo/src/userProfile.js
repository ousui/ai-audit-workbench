import axios from 'axios';

export async function loadUserProfile(userId) {
  const token = window.localStorage.getItem('access_token');
  const response = await axios.get(`/api/users/${userId}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  window.sessionStorage.setItem('last_user_id', String(userId));
  return response.data;
}

export function saveLoginToken(token) {
  localStorage.setItem('access_token', token);
}
