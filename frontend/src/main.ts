import { mount } from 'svelte';
import App from './App.svelte';
import './style.css';
const theme = window.matchMedia('(prefers-color-scheme: dark)');
const applyTheme = () =>
    document.documentElement.classList.toggle('dark', theme.matches);
applyTheme();
theme.addEventListener('change', applyTheme);
mount(App, { target: document.getElementById('app')! });
