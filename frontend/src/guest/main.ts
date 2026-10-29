import { mount } from 'svelte'
import '../styles/app.css'
import GuestApp from './GuestApp.svelte'

mount(GuestApp, { target: document.getElementById('app')! })
